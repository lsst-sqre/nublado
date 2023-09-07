"""Generic Kubernetes object storage including list and delete.

Provides a generic Kubernetes object management class and instantiations of
that class for Kubernetes object types that support list and delete (as well
as create and read, provided by the superclass). Storage classes for object
types that only need those operations are provided here; more complex storage
classes with other operations are defined in their own modules.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Generic, TypeVar

from kubernetes_asyncio import client
from kubernetes_asyncio.client import ApiClient, ApiException, V1Service
from structlog.stdlib import BoundLogger

from ...constants import KUBERNETES_DELETE_TIMEOUT
from ...exceptions import KubernetesError
from ...models.domain.kubernetes import KubernetesModel, WatchEventType
from .creator import KubernetesObjectCreator
from .watcher import KubernetesWatcher

#: Type of Kubernetes object being manipulated.
T = TypeVar("T", bound=KubernetesModel)

__all__ = [
    "KubernetesObjectDeleter",
    "ServiceStorage",
    "T",
]


class KubernetesObjectDeleter(KubernetesObjectCreator, Generic[T]):
    """Generic Kubernetes object storage supporting list and delete.

    This class provides a wrapper around any Kubernetes object type that
    implements create, read, list, and delete with logging, exception
    conversion, and waiting for deletion to complete. It is separate from
    `KubernetesObjectCreator` primarily to avoid having to implement the list
    and delete methods in the mock for every object type we manage, even if we
    never call list and delete.

    This class is not meant to be used directly by code outside of the
    Kubernetes storage layer. Use one of the kind-specific watcher classes
    built on top of it instead.

    Parameters
    ----------
    create_method
        Method to create this type of object.
    delete_method
        Method to delete this type of object.
    list_method
        Method to list all of this type of object.
    read_method
        Method to read this type of object.
    object_type
        Type of object being acted on.
    kind
        Kubernetes kind of object being acted on.
    logger
        Logger to use.
    """

    def __init__(
        self,
        *,
        create_method: Callable[..., Awaitable[Any]],
        delete_method: Callable[..., Awaitable[Any]],
        list_method: Callable[..., Awaitable[Any]],
        read_method: Callable[..., Awaitable[Any]],
        object_type: type[T],
        kind: str,
        logger: BoundLogger,
    ) -> None:
        super().__init__(
            create_method=create_method,
            read_method=read_method,
            object_type=object_type,
            kind=kind,
            logger=logger,
        )
        self._delete = delete_method
        self._list = list_method

    async def create(
        self, namespace: str, body: T, *, replace: bool = False
    ) -> None:
        """Create a new Kubernetes object.

        Parameters
        ----------
        namespace
            Namespace of the object.
        body
            New object.
        replace
            If `True` and an object of that name already exists in that
            namespace, delete the existing object and then try again.

        Raises
        ------
        KubernetesError
            Raised for exceptions from the Kubernetes API server.
        """
        try:
            await super().create(namespace, body)
        except KubernetesError as e:
            if replace and e.status == 409:
                name = body.metadata.name
                msg = f"{self._kind} already exists, deleting and recreating"
                self._logger.warning(msg, name=name, namespace=namespace)
                await self.delete(name, namespace, wait=True)
                await super().create(namespace, body)
            else:
                raise

    async def delete(
        self, name: str, namespace: str, *, wait: bool = False
    ) -> None:
        """Delete a Kubernetes object.

        If the object does not exist, this is silently treated as success.

        Parameters
        ----------
        name
            Name of the object.
        namespace
            Namespace of the object.
        wait
            Whether to wait for the object to be deleted.

        Raises
        ------
        KubernetesError
            Raised for exceptions from the Kubernetes API server.
        """
        msg = f"Deleting {self._kind}"
        self._logger.debug(msg, name=name, namespace=namespace)
        try:
            await self._delete(name, namespace)
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
            await self.wait_for_deletion(name, namespace)

    async def list(self, namespace: str) -> list[T]:
        """List all objects of the appropriate kind in the namespace.

        Parameters
        ----------
        namespace
            Namespace to list.

        Returns
        -------
        list
            List of objects found.

        Raises
        ------
        KubernetesError
            Raised for exceptions from the Kubernetes API server.
        """
        try:
            objs = await self._list(namespace)
        except ApiException as e:
            raise KubernetesError.from_exception(
                "Error listing objects",
                e,
                kind=self._kind,
                namespace=namespace,
            ) from e
        return objs.items

    async def wait_for_deletion(self, name: str, namespace: str) -> None:
        """Wait for an object deletion to complete.

        Parameters
        ----------
        name
            Name of the object.
        namespace
            Namespace of the object.

        Raises
        ------
        KubernetesError
            Raised for exceptions from the Kubernetes API server.
        TimeoutError
            Raised if the object is not deleted within the delete timeout.
        """
        obj = await self.read(name, namespace)
        if not obj:
            return

        # Wait for the object to be deleted.
        watcher = KubernetesWatcher(
            method=self._list,
            object_type=self._type,
            kind=self._kind,
            name=name,
            namespace=namespace,
            resource_version=obj.metadata.resource_version,
            timeout=KUBERNETES_DELETE_TIMEOUT,
            logger=self._logger,
        )
        try:
            async for event in watcher.watch():
                if event.action == WatchEventType.DELETED:
                    return
        except TimeoutError:
            # If the watch had to be restarted because the resource version
            # was too old and the object was deleted while the watch was
            # restarting, we could have missed the delete event. Therefore,
            # before timing out, do a final check to see if the object is
            # gone.
            if not await self.read(name, namespace):
                return
            raise
        finally:
            await watcher.close()

        # This should be impossible; someone called stop on the watcher.
        raise RuntimeError("Wait for object deletion unexpectedly stopped")


class ServiceStorage(KubernetesObjectDeleter):
    """Storage layer for ``Service`` objects.

    Parameters
    ----------
    api_client
        Kubernetes API client.
    logger
        Logger to use.
    """

    def __init__(self, api_client: ApiClient, logger: BoundLogger) -> None:
        api = client.CoreV1Api(api_client)
        super().__init__(
            create_method=api.create_namespaced_service,
            delete_method=api.delete_namespaced_service,
            list_method=api.list_namespaced_service,
            read_method=api.read_namespaced_service,
            object_type=V1Service,
            kind="Service",
            logger=logger,
        )
