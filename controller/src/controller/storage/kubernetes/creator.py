"""Generic Kubernetes object storage supporting only create and read.

Provides a generic Kubernetes object management class and instantiations of
that class for Kubernetes object types that only support create and read.
This is sufficient for a lot of object types the lab controller manipulates.
Storage classes for object types that only need those operations are provided
here.

For object types that need to support other operations, see
`~controller.storage.kubernetes.deleter.KubernetesObjectDeleter`, which
subclasses `KubernetesObjectCreator` and adds list and delete support, and its
subclasses.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from kubernetes_asyncio import client
from kubernetes_asyncio.client import (
    ApiClient,
    ApiException,
    V1ConfigMap,
    V1NetworkPolicy,
    V1ResourceQuota,
    V1Secret,
)
from structlog.stdlib import BoundLogger

from ...exceptions import KubernetesError
from ...models.domain.kubernetes import KubernetesModel
from ...timeout import Timeout

__all__ = [
    "ConfigMapStorage",
    "KubernetesObjectCreator",
    "NetworkPolicyStorage",
    "ResourceQuotaStorage",
    "SecretStorage",
]


class KubernetesObjectCreator[T: KubernetesModel]:
    """Generic Kubernetes object storage supporting create and read.

    This class provides a wrapper around any Kubernetes object type that
    implements create and read operations with logging and exception
    conversion.

    This class is not meant to be used directly by code outside of the
    Kubernetes storage layer. Use one of the kind-specific watcher classes
    built on top of it instead.

    Parameters
    ----------
    create_method
        Method to create this type of object.
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
        read_method: Callable[..., Awaitable[Any]],
        object_type: type[T],
        kind: str,
        logger: BoundLogger,
    ) -> None:
        self._create = create_method
        self._read = read_method
        self._type = object_type
        self._kind = kind
        self._logger = logger

    async def create(self, namespace: str, body: T, timeout: Timeout) -> None:
        """Create a new Kubernetes object.

        Parameters
        ----------
        namespace
            Namespace of the object.
        body
            New object.
        timeout
            Timeout on operation.

        Raises
        ------
        KubernetesError
            Raised for exceptions from the Kubernetes API server.
        """
        msg = f"Creating {self._kind}"
        self._logger.debug(msg, name=body.metadata.name, namespace=namespace)
        try:
            await self._create(
                namespace, body, _request_timeout=timeout.left()
            )
        except ApiException as e:
            raise KubernetesError.from_exception(
                "Error creating object",
                e,
                kind=self._kind,
                namespace=namespace,
                name=body.metadata.name,
            ) from e

    async def read(
        self, name: str, namespace: str, timeout: Timeout
    ) -> T | None:
        """Read a Kubernetes object.

        Parameters
        ----------
        name
            Name of the object.
        namespace
            Namespace of the object.
        timeout
            Timeout on operation.

        Returns
        -------
        typing.Any or None
            Kubernetes object, or `None` if it does not exist.

        Raises
        ------
        KubernetesError
            Raised for exceptions from the Kubernetes API server.
        """
        try:
            return await self._read(
                name, namespace, _request_timeout=timeout.left()
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


class ConfigMapStorage(KubernetesObjectCreator[V1ConfigMap]):
    """Storage layer for ``ConfigMap`` objects.

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
            create_method=api.create_namespaced_config_map,
            read_method=api.read_namespaced_config_map,
            object_type=V1ConfigMap,
            kind="ConfigMap",
            logger=logger,
        )


class NetworkPolicyStorage(KubernetesObjectCreator[V1NetworkPolicy]):
    """Storage layer for ``NetworkPolicy`` objects.

    Parameters
    ----------
    api_client
        Kubernetes API client.
    logger
        Logger to use.
    """

    def __init__(self, api_client: ApiClient, logger: BoundLogger) -> None:
        api = client.NetworkingV1Api(api_client)
        super().__init__(
            create_method=api.create_namespaced_network_policy,
            read_method=api.read_namespaced_network_policy,
            object_type=V1NetworkPolicy,
            kind="NetworkPolicy",
            logger=logger,
        )


class ResourceQuotaStorage(KubernetesObjectCreator[V1ResourceQuota]):
    """Storage layer for ``ResourceQuota`` objects.

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
            create_method=api.create_namespaced_resource_quota,
            read_method=api.read_namespaced_resource_quota,
            object_type=V1ResourceQuota,
            kind="ResourceQuota",
            logger=logger,
        )


class SecretStorage(KubernetesObjectCreator[V1Secret]):
    """Storage layer for ``Secret`` objects.

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
            create_method=api.create_namespaced_secret,
            read_method=api.read_namespaced_secret,
            object_type=V1Secret,
            kind="Secret",
            logger=logger,
        )
