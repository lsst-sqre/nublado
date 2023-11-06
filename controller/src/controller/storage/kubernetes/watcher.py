"""Watch a Kubernetes namespace or cluster for events."""

from __future__ import annotations

import asyncio
import math
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Generic, Self, TypeVar

from kubernetes_asyncio.client import ApiException
from kubernetes_asyncio.watch import Watch
from safir.datetime import current_datetime
from structlog.stdlib import BoundLogger

from ...exceptions import KubernetesError
from ...models.domain.kubernetes import WatchEventType

#: Type of Kubernetes object being watched (`dict` for custom objects).
T = TypeVar("T")

__all__ = [
    "KubernetesWatcher",
    "T",
    "WatchEvent",
]


@dataclass
class WatchEvent(Generic[T]):
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
        """Create a `KubernetesWatchEvent` from a watch event.

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


class KubernetesWatcher(Generic[T]):
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
        Timeout for the watch.
    logger
        Logger to use.

    Raises
    ------
    ValueError
        Raised if ``name`` and ``involved_object`` are both specified, or if
        ``timeout`` is specified but is less than zero.
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
        timeout: timedelta | None = None,
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
        if timeout:
            timeout_seconds = int(math.ceil(timeout.total_seconds()))
            if timeout_seconds <= 0:
                raise ValueError("Watch timeout specified but <= 0")
        if name:
            if involved_object:
                raise ValueError("name and involved_object both specified")
            field_selector = f"metadata.name={name}"
        elif involved_object:
            field_selector = f"involvedObject.name={involved_object}"
        else:
            field_selector = None
        args = {
            "field_selector": field_selector,
            "group": group,
            "version": version,
            "plural": plural,
            "namespace": namespace,
            "resource_version": resource_version,
            "timeout_seconds": timeout_seconds if timeout else None,
            "_request_timeout": timeout_seconds if timeout else None,
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
        start = current_datetime(microseconds=True)
        while True:
            try:
                async with self._watch.stream(self._method, **self._args) as s:
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
                if self._timeout:
                    elapsed = current_datetime(microseconds=True) - start
                    if elapsed + timedelta(seconds=1) < self._timeout:
                        new_timeout = self._timeout - elapsed
                        new_timeout_seconds = int(new_timeout.total_seconds())
                        args["timeout_seconds"] = new_timeout_seconds
                        args["_request_timeout"] = new_timeout_seconds
                        continue
                    elapsed_seconds = elapsed.total_seconds()
                    msg = f"Event watch timed out after {elapsed_seconds}s"
                    raise TimeoutError(msg)
                else:
                    raise TimeoutError("Event watch timed out by server")
            except ApiException as e:
                if e.status == 410 and "resource_version" in args:
                    version = args["resource_version"]
                    msg = f"Resource version {version} expired, retrying watch"
                    self._logger.info(msg)
                    del args["resource_version"]
                    continue

                # We have seen one instance where Kubernetes returned a 410
                # error even though no resourceVersion was set in the call.
                # The Kubernetes documentation implies that this can happen if
                # there are long delays between reportable events. Retry those
                # as well, relying on our timeout to stop us, but wait one
                # second so that we don't spam the Kubernetes controller with
                # requests if every request is returning 410.
                if e.status == 410 and self._timeout:
                    msg = "Watch expired (no resource version), retrying"
                    self._logger.info(msg)
                    await asyncio.sleep(1)
                    continue

                raise KubernetesError.from_exception(
                    "Error watching objects",
                    e,
                    kind=self._kind,
                    namespace=self._namespace,
                    name=self._name,
                ) from e
