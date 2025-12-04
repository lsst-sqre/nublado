"""Watch a Kubernetes namespace or cluster for events."""

import math
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Self

from kubernetes_asyncio.client import ApiException
from kubernetes_asyncio.watch import Watch
from structlog.stdlib import BoundLogger

from ...exceptions import KubernetesError
from ...models.domain.kubernetes import WatchEventType
from ...timeout import Timeout

__all__ = [
    "KubernetesWatcher",
    "WatchEvent",
]


@dataclass
class WatchEvent[T]:
    """Parsed event from a Kubernetes watch.

    This model is intended only for use within the Kubernetes storage layer.
    It is interpreted by the callers of the generic watch class inside the
    per-object Kubernetes storage classes.
    """

    action: WatchEventType
    """Action the event represents."""

    object: T
    """Affected Kubernetes object."""

    @classmethod
    def from_event(cls, event: dict[str, Any], object_type: type[T]) -> Self:
        """Create a `WatchEvent` from a watch event.

        Parameters
        ----------
        event
            Event as returned by the Kubernetes watch API.
        object_type
            Expected type of the object.

        Raises
        ------
        TypeError
            Raised if the type of the object in the watch event was incorrect.
        """
        action = WatchEventType(event["type"])
        if object_type.__name__ == "dict":
            return cls(action=action, object=event["raw_object"])
        obj = event["object"]
        if not isinstance(obj, object_type):
            real_type = type(obj).__name__
            expected_type = object_type.__name__
            msg = f"Watch object was of type {real_type}, not {expected_type}"
            raise TypeError(msg)
        return cls(action=action, object=obj)


class KubernetesWatcher[T]:
    """Watch Kubernetes for events.

    This wrapper around the watch API of the Kubernetes client implements
    retries and resource version handling and fixes typing problems when used
    with the Safir `~safir.testing.kubernetes.MockKubernetesApi` mock. The
    latter confuses the type detection in the ``kubernetes_asyncio`` library,
    which is handled here by passing in an explicit return type.

    This class is not meant to be used directly by code outside of the
    Kubernetes storage layer. Use one of the kind-specific watcher classes
    built on top of it instead.

    Parameters
    ----------
    method
        API list method that supports the watch API.
    object_type
        Type of object being watched. This cannot be autodiscovered from the
        method because of the problems with docstring parsing and therefore
        must be provided by the caller and must match the type of object
        returned by the method. For custom objects, this should be a `dict`
        type.
    kind
        Kubernetes kind of object being watched, for error reporting.
    name
        Name of object to watch. Cannot be used with ``involved_object``.
    namespace
        Namespace to watch.
    group
        Group of custom object.
    version
        Version of custom object.
    plural
        Plural of custom object.
    involved_object
        Involved object to watch (used when watching events). Cannot be used
        with ``name``.
    resource_version
        Resource version at which to start the watch.
    timeout
        Timeout for the watch. This may be `None`, in which case the watch
        continues until cancelled or until the iterator is no longer called.
    logger
        Logger to use.

    Raises
    ------
    ValueError
        Raised if ``name`` and ``involved_object`` are both specified.
    """

    def __init__(
        self,
        *,
        method: Callable[..., Awaitable[Any]],
        object_type: type[T],
        kind: str,
        name: str | None = None,
        namespace: str | None = None,
        group: str | None = None,
        version: str | None = None,
        plural: str | None = None,
        involved_object: str | None = None,
        resource_version: str | None = None,
        timeout: Timeout | None,
        logger: BoundLogger,
    ) -> None:
        self._method = method
        self._type = object_type
        self._kind = kind
        self._namespace = namespace
        self._name = name
        self._logger = logger
        self._timeout = timeout
        self._stopped = False

        # Build the arguments to the method being watched.
        if name:
            if involved_object:
                raise ValueError("name and involved_object both specified")
            field_selector = f"metadata.name={name}"
        elif involved_object:
            field_selector = f"involvedObject.name={involved_object}"
        else:
            field_selector = None
        args: dict[str, str | float | None] = {
            "field_selector": field_selector,
            "group": group,
            "version": version,
            "plural": plural,
            "namespace": namespace,
            "resource_version": resource_version,
        }
        self._args = {k: v for k, v in args.items() if v is not None}

        # Passing in an explicit type should not be necessary, but the
        # kubernetes_asyncio module determines the type of a method by parsing
        # its docstring and expects native Sphinx markup. This means that if
        # the Safir MockKubernetesApi mock API is in use, the automatic type
        # discovery breaks, because we use the numpy convention.
        self._watch = Watch(return_type=object_type)

    async def close(self) -> None:
        """Close the internal API client used by the watch API."""
        self._watch.stop()
        await self._watch.close()

    def stop(self) -> None:
        """Stop a watch in progress."""
        self._watch.stop()
        self._stopped = True

    async def watch(self) -> AsyncIterator[WatchEvent[T]]:
        """Watch Kubernetes for events.

        If we started watching with a specific resource version, that resource
        version may be too old to still be known to Kubernetes, in which case
        the API call returns a 410 error and we should retry without a
        resource version. This is handled automatically. Unfortunately, this
        has a race condition where we may miss events that come in after the
        error is returned but before we retry the API call.

        Yields
        ------
        dict
            Event as returned by the Kubernetes API, without further parsing.

        Raises
        ------
        KubernetesError
            Raised for exceptions from the Kubernetes API server during the
            watch.
        TimeoutError
            Raised if the timeout was reached.
        """
        args = self._args.copy()
        while True:
            if self._timeout:
                left = self._timeout.left()
                args["_request_timeout"] = left
                args["timeout_seconds"] = math.ceil(left)
            try:
                async with self._watch.stream(self._method, **args) as s:
                    async for event in s:
                        yield WatchEvent.from_event(event, self._type)

                # Client timeouts will raise TimeoutError, but server timeouts
                # will just end the iterator. Calling the stop method will
                # also end the iterator; distinguish by looking at
                # self._stopped.
                #
                # The server may time us out before our configured timeout
                # (the Kubernetes control plane implements some global maximum
                # timeouts), so we have to check for that case and retry with
                # a reduced timeout if it happens.
                if self._stopped:
                    break
                if not self._timeout:
                    raise TimeoutError("Event watch timed out by server")
            except ApiException as e:
                if e.status == 410:
                    if "resource_version" in args:
                        rv = args["resource_version"]
                        msg = f"Resource version {rv} expired, retrying watch"
                        self._logger.info(msg)
                        del args["resource_version"]
                    else:
                        # We can get a 410 error even when no resource version
                        # is specified if there are long delays between
                        # reportable events. Retry those as well.
                        msg = "Watch expired (no resource version), retrying"
                        self._logger.info(msg)
                    continue

                raise KubernetesError.from_exception(
                    "Error watching objects",
                    e,
                    kind=self._kind,
                    namespace=self._namespace,
                    name=self._name,
                ) from e
