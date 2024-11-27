"""Generic Kubernetes object storage including list and delete.

Provides a generic Kubernetes object management class and instantiations of
that class for Kubernetes object types that support list and delete (as well
as create and read, provided by the superclass). Storage classes for object
types that only need those operations are provided here; more complex storage
classes with other operations are defined in their own modules.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any, Generic, TypeVar

from kubernetes_asyncio import client
from kubernetes_asyncio.client import (
    ApiClient,
    ApiException,
    V1DeleteOptions,
    V1Job,
    V1PersistentVolumeClaim,
    V1Service,
)
from structlog.stdlib import BoundLogger

from ...exceptions import ControllerTimeoutError, KubernetesError
from ...models.domain.kubernetes import (
    KubernetesModel,
    PropagationPolicy,
    WatchEventType,
)
from ...timeout import Timeout
from .creator import KubernetesObjectCreator
from .watcher import KubernetesWatcher

#: Type of Kubernetes object being manipulated.
T = TypeVar("T", bound=KubernetesModel)

__all__ = [
    "JobStorage",
    "KubernetesObjectDeleter",
    "PersistentVolumeClaimStorage",
    "ServiceStorage",
    "T",
]


class KubernetesObjectDeleter(KubernetesObjectCreator, Generic[T]):
    """Generic Kubernetes object storage supporting list and delete.

    This class provides a wrapper around any Kubernetes object type that
    implements create, read, list, and delete with logging, exception
    conversion, and waiting for deletion to complete. It is separate from
    `~controller.storage.kubernetes.creator.KubernetesObjectCreator` primarily
    to avoid having to implement the list and delete methods in the mock for
    every object type we manage, even if we never call list and delete.

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
        self,
        namespace: str,
        body: T,
        timeout: Timeout,
        *,
        replace: bool = False,
        propagation_policy: PropagationPolicy | None = None,
    ) -> None:
        """Create a new Kubernetes object.

        Parameters
        ----------
        namespace
            Namespace of the object.
        body
            New object.
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
        try:
            await super().create(namespace, body, timeout)
        except KubernetesError as e:
            if replace and e.status == 409:
                name = body.metadata.name
                msg = f"{self._kind} already exists, deleting and recreating"
                self._logger.warning(msg, name=name, namespace=namespace)
                await self.delete(
                    name,
                    namespace,
                    timeout,
                    wait=True,
                    propagation_policy=propagation_policy,
                )
                await super().create(namespace, body, timeout)
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
        grace_period: timedelta | None = None,
    ) -> None:
        """Delete a Kubernetes object.

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
            Whether to wait for the object to be deleted.
        propagation_policy
            Propagation policy for the object deletion.
        grace_period
            How long to wait for the object to clean up before deleting it.
            Primarily of use for pods, where it defines how long Kubernetes
            will wait between sending SIGTERM and sending SIGKILL to a pod
            process. The default for pods if no grace period is set is 30s as
            of Kubernetes 1.27.1. This will be truncated to integer seconds.

        Raises
        ------
        ControllerTimeoutError
            Raised if the timeout expired waiting for deletion.
        KubernetesError
            Raised for exceptions from the Kubernetes API server.
        TimeoutError
            Raised if the timeout expired.
        """
        extra_args: dict[str, str | float] = {
            "_request_timeout": timeout.left()
        }
        body = None
        if propagation_policy:
            extra_args["propagation_policy"] = propagation_policy.value
        if grace_period:
            grace = int(grace_period.total_seconds())

            # It's not clear whether the grace period has to be specified in
            # both the delete options body and as a query parameter, but
            # kubespawner sets both, so we'll do the same. I suspect that only
            # one or the other is needed.
            body = V1DeleteOptions(grace_period_seconds=grace)
            extra_args["grace_period_seconds"] = grace
        self._logger.debug(
            f"Deleting {self._kind}",
            name=name,
            namespace=namespace,
            options=extra_args,
        )
        try:
            await self._delete(name, namespace, body=body, **extra_args)
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
        self,
        namespace: str,
        timeout: Timeout,
        *,
        label_selector: str | None = None,
    ) -> list[T]:
        """List all objects of the appropriate kind in the namespace.

        Parameters
        ----------
        namespace
            Namespace to list.
        timeout
            Timeout on operation.
        label_selector
            Filter the returned list by the given label selector expression.

        Returns
        -------
        list
            List of objects found.

        Raises
        ------
        KubernetesError
            Raised for exceptions from the Kubernetes API server.
        TimeoutError
            Raised if the timeout expired.
        """
        extra_args: dict[str, str | float] = {
            "_request_timeout": timeout.left()
        }
        if label_selector:
            extra_args["label_selector"] = label_selector
        try:
            objs = await self._list(namespace, **extra_args)
        except ApiException as e:
            raise KubernetesError.from_exception(
                "Error listing objects",
                e,
                kind=self._kind,
                namespace=namespace,
            ) from e
        return objs.items

    async def wait_for_deletion(
        self, name: str, namespace: str, timeout: Timeout
    ) -> None:
        """Wait for an object deletion to complete.

        Parameters
        ----------
        name
            Name of the object.
        namespace
            Namespace of the object.
        timeout
            How long to wait for the object to be deleted.

        Raises
        ------
        ControllerTimeoutError
            Raised if the timeout expired.
        KubernetesError
            Raised for exceptions from the Kubernetes API server.
        """
        logger = self._logger.bind(name=name, namespace=namespace)
        obj = await self.read(name, namespace, timeout)
        if not obj:
            return

        # Wait for the object to be deleted.
        watch_timeout = timeout.partial(timedelta(seconds=timeout.left() - 2))
        watcher = KubernetesWatcher(
            method=self._list,
            object_type=self._type,
            kind=self._kind,
            name=name,
            namespace=namespace,
            resource_version=obj.metadata.resource_version,
            timeout=watch_timeout,
            logger=logger,
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


class JobStorage(KubernetesObjectDeleter):
    """Storage layer for ``Job`` objects.

    Parameters
    ----------
    api_client
        Kubernetes API client.
    logger
        Logger to use.
    """

    def __init__(self, api_client: ApiClient, logger: BoundLogger) -> None:
        api = client.BatchV1Api(api_client)
        super().__init__(
            create_method=api.create_namespaced_job,
            delete_method=api.delete_namespaced_job,
            list_method=api.list_namespaced_job,
            read_method=api.read_namespaced_job,
            object_type=V1Job,
            kind="Job",
            logger=logger,
        )


class PersistentVolumeClaimStorage(KubernetesObjectDeleter):
    """Storage layer for ``PersistentVolumeClaim`` objects.

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
            create_method=api.create_namespaced_persistent_volume_claim,
            delete_method=api.delete_namespaced_persistent_volume_claim,
            list_method=api.list_namespaced_persistent_volume_claim,
            read_method=api.read_namespaced_persistent_volume_claim,
            object_type=V1PersistentVolumeClaim,
            kind="PersistentVolumeClaim",
            logger=logger,
        )


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
