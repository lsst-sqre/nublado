"""Storage layer for Kubernetes custom objects objects."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from kubernetes_asyncio import client
from kubernetes_asyncio.client import ApiClient, ApiException
from structlog.stdlib import BoundLogger

from ...exceptions import ControllerTimeoutError, KubernetesError
from ...models.domain.kubernetes import PropagationPolicy, WatchEventType
from ...timeout import Timeout
from .watcher import KubernetesWatcher

__all__ = [
    "CustomStorage",
    "GafaelfawrIngressStorage",
]


class CustomStorage:
    """Storage layer for Kubernetes custom objects.

    Normally, this class should be subclassed to specialize it for a specific
    custom object type, which provides a slightly nicer API, but it can be
    used as-is if desired.

    Parameters
    ----------
    api_client
        Kubernetes API client.
    group
        API group for the custom objects to handle.
    version
        API version for the custom objects to handle.
    plural
        API plural under which those custom objects are managed.
    kind
        Name of the custom object kind, used for error reporting.
    logger
        Logger to use.
    """

    def __init__(
        self,
        *,
        api_client: ApiClient,
        group: str,
        version: str,
        plural: str,
        kind: str,
        logger: BoundLogger,
    ) -> None:
        self._api = client.CustomObjectsApi(api_client)
        self._group = group
        self._version = version
        self._plural = plural
        self._kind = kind
        self._logger = logger

    async def create(
        self,
        namespace: str,
        body: dict[str, Any],
        timeout: Timeout,
        *,
        replace: bool = False,
        propagation_policy: PropagationPolicy | None = None,
    ) -> None:
        """Create a new custom object.

        Parameters
        ----------
        namespace
            Namespace of the object.
        body
            Custom object to create.
        timeout
            Timeout on operation.
        replace
            If `True` and an object of that name already exists in that
            namespace, delete the existing object and then try again.
        propagation_policy
            Propagation policy for the object deletion when deleting a
            conflicting object.

        Raises
        ------
        ControllerTimeoutError
            Raised if the timeout expired waiting for deletion.
        KubernetesError
            Raised for exceptions from the Kubernetes API server.
        TimeoutError
            Raised if the timeout expired.
        """
        name = body["metadata"]["name"]
        msg = f"Creating {self._kind}"
        self._logger.debug(msg, name=name, namespace=namespace)
        try:
            await self._create(namespace, body, timeout)
        except KubernetesError as e:
            if replace and e.status == 409:
                msg = f"{self._kind} already exists, deleting and recreating"
                self._logger.warning(msg, name=name, namespace=namespace)
                await self.delete(name, namespace, timeout, wait=True)
                await self._create(namespace, body, timeout)
            else:
                raise

    async def delete(
        self,
        name: str,
        namespace: str,
        timeout: Timeout,
        *,
        wait: bool = False,
        propagation_policy: PropagationPolicy | None = None,
    ) -> None:
        """Delete a custom object.

        If the object does not exist, this is silently treated as success.

        Parameters
        ----------
        name
            Name of the object.
        namespace
            Namespace of the object.
        timeout
            Timeout on operation.
        wait
            Whether to wait for the custom object to be deleted.
        propagation_policy
            Propagation policy for the object deletion.

        Raises
        ------
        ControllerTimeoutError
            Raised if the timeout expired waiting for deletion.
        KubernetesError
            Raised for exceptions from the Kubernetes API server.
        TimeoutError
            Raised if the timeout expired.
        """
        msg = f"Deleting {self._kind}"
        self._logger.debug(msg, name=name, namespace=namespace)
        try:
            async with timeout.enforce():
                await self._api.delete_namespaced_custom_object(
                    self._group,
                    self._version,
                    namespace,
                    self._plural,
                    name,
                    _request_timeout=timeout.left(),
                )
        except ApiException as e:
            if e.status == 404:
                return
            raise KubernetesError.from_exception(
                "Error deleting object",
                e,
                kind=self._kind,
                namespace=namespace,
                name=name,
            ) from e
        if wait:
            await self.wait_for_deletion(name, namespace, timeout)

    async def list(
        self, namespace: str, timeout: Timeout
    ) -> list[dict[str, Any]]:
        """List the custom objects in a namespace.

        Parameters
        ----------
        namespace
            Namespace in which to list custom objects.
        timeout
            Timeout on operation.

        Returns
        -------
        list of dict
            List of custom objects found.

        Raises
        ------
        KubernetesError
            Raised for exceptions from the Kubernetes API server.
        TimeoutError
            Raised if the timeout expired.
        """
        try:
            async with timeout.enforce():
                objs = await self._api.list_namespaced_custom_object(
                    self._group,
                    self._version,
                    namespace,
                    self._plural,
                    _request_timeout=timeout.left(),
                )
        except ApiException as e:
            raise KubernetesError.from_exception(
                "Error listing objects",
                e,
                kind=self._kind,
                namespace=namespace,
            ) from e
        return objs.items

    async def read(
        self, name: str, namespace: str, timeout: Timeout
    ) -> dict[str, Any] | None:
        """Read a custom object.

        Parameters
        ----------
        name
            Name of the custom object.
        namespace
            Namespace of the custom object.
        timeout
            Timeout on operation.

        Returns
        -------
        dict or None
            Custom object, or `None` if it does not exist.

        Raises
        ------
        KubernetesError
            Raised for exceptions from the Kubernetes API server.
        TimeoutError
            Raised if the timeout expired.
        """
        try:
            async with timeout.enforce():
                return await self._api.get_namespaced_custom_object(
                    self._group,
                    self._version,
                    namespace,
                    self._plural,
                    name,
                    _request_timeout=timeout.left(),
                )
        except ApiException as e:
            if e.status == 404:
                return None
            raise KubernetesError.from_exception(
                "Error reading object",
                e,
                kind=self._kind,
                namespace=namespace,
                name=name,
            ) from e

    async def wait_for_deletion(
        self,
        name: str,
        namespace: str,
        timeout: Timeout,
    ) -> None:
        """Wait for a custom object deletion to complete.

        Parameters
        ----------
        name
            Name of the custom object.
        namespace
            Namespace of the custom object.
        timeout
            How long to wait for the object to be deleted.

        Raises
        ------
        ControllerTimeoutError
            Raised if the timeout expired.
        KubernetesError
            Raised for exceptions from the Kubernetes API server.
        """
        obj = await self.read(name, namespace, timeout)
        if not obj:
            return

        # Wait for the object to be deleted.
        watch_timeout = timeout.partial(timedelta(seconds=timeout.left() - 2))
        watcher = KubernetesWatcher(
            method=self._api.list_namespaced_custom_object,
            object_type=dict[str, Any],
            kind=self._kind,
            name=name,
            namespace=namespace,
            group=self._group,
            version=self._version,
            plural=self._plural,
            resource_version=obj["metadata"].get("resource_version"),
            timeout=watch_timeout,
            logger=self._logger,
        )
        try:
            async with watch_timeout.enforce():
                async for event in watcher.watch():
                    if event.action == WatchEventType.DELETED:
                        return
        except ControllerTimeoutError:
            # If the watch had to be restarted because the resource version
            # was too old and the object was deleted while the watch was
            # restarting, we could have missed the delete event. Therefore,
            # before timing out, do a final check with a short timeout to see
            # if the object is gone.
            read_timeout = timeout.partial(timedelta(seconds=2))
            if not await self.read(name, namespace, read_timeout):
                return
            raise
        finally:
            await watcher.close()

        # This should be impossible; someone called stop on the watcher.
        raise RuntimeError("Wait for object deletion unexpectedly stopped")

    async def _create(
        self, namespace: str, body: dict[str, Any], timeout: Timeout
    ) -> None:
        """Create a custom object (without recreation on conflict).

        Parameters
        ----------
        namespace
            Namespace in which to create the object.
        body
            Namespace object to create.
        timeout
            Timeout on operation.

        Raises
        ------
        KubernetesError
            Raised for exceptions from the Kubernetes API server.
        TimeoutError
            Raised if the timeout expired.
        """
        name = body["metadata"]["name"]
        try:
            async with timeout.enforce():
                await self._api.create_namespaced_custom_object(
                    self._group,
                    self._version,
                    namespace,
                    self._plural,
                    body,
                    _request_timeout=timeout.left(),
                )
        except ApiException as e:
            raise KubernetesError.from_exception(
                "Error creating object",
                e,
                kind=self._kind,
                namespace=namespace,
                name=name,
            ) from e


class GafaelfawrIngressStorage(CustomStorage):
    """Storage layer for ``GafaelfawrIngress`` objects.

    Parameters
    ----------
    api_client
        Kubernetes API client.
    logger
        Logger to use.
    """

    def __init__(self, api_client: ApiClient, logger: BoundLogger) -> None:
        super().__init__(
            api_client=api_client,
            group="gafaelfawr.lsst.io",
            version="v1alpha1",
            plural="gafaelfawringresses",
            kind="GafaelfawrIngress",
            logger=logger,
        )
