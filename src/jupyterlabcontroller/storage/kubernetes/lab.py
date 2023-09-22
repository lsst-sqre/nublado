"""Kubernetes storage layer for user labs."""

from __future__ import annotations

from kubernetes_asyncio.client import ApiClient, V1Secret
from structlog.stdlib import BoundLogger

from ...constants import LAB_STOP_GRACE_PERIOD
from ...exceptions import MissingSecretError
from ...models.domain.lab import LabObjects
from .creator import (
    ConfigMapStorage,
    NetworkPolicyStorage,
    PersistentVolumeClaimStorage,
    ResourceQuotaStorage,
    SecretStorage,
)
from .deleter import ServiceStorage
from .namespace import NamespaceStorage
from .pod import PodStorage

__all__ = ["LabStorage"]


class LabStorage:
    """Kubernetes storage layer for user labs.

    Parameters
    ----------
    api_client
        Kubernetes API client.
    logger
        Logger to use.

    Notes
    -----
    This class isn't strictly necessary; instead, the lab service could
    call the storage layers for individual Kubernetes objects directly. But
    there are enough different objects in play that adding a thin layer to
    wrangle the storage objects makes the lab service easier to follow.
    """

    def __init__(self, api_client: ApiClient, logger: BoundLogger) -> None:
        self._logger = logger
        self._config_map = ConfigMapStorage(api_client, logger)
        self._namespace = NamespaceStorage(api_client, logger)
        self._network_policy = NetworkPolicyStorage(api_client, logger)
        self._pod = PodStorage(api_client, logger)
        self._pvc = PersistentVolumeClaimStorage(api_client, logger)
        self._quota = ResourceQuotaStorage(api_client, logger)
        self._secret = SecretStorage(api_client, logger)
        self._service = ServiceStorage(api_client, logger)

    async def create(self, objects: LabObjects) -> None:
        """Create all of the Kubernetes objects for a user's lab.

        Parameters
        ----------
        objects
            Kubernetes objects making up the user's lab.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        namespace = objects.namespace.metadata.name
        await self._namespace.create(objects.namespace)
        for pvc in objects.pvcs:
            await self._pvc.create(namespace, pvc)
        for config_map in objects.config_maps:
            await self._config_map.create(namespace, config_map)
        for secret in objects.secrets:
            await self._secret.create(namespace, secret)
        if objects.quota:
            await self._quota.create(namespace, objects.quota)
        await self._network_policy.create(namespace, objects.network_policy)
        await self._service.create(namespace, objects.service)
        await self._pod.create(namespace, objects.pod)

    async def delete_namespace(self, name: str) -> None:
        """Delete a namespace, waiting for deletion to finish.

        Parameters
        ----------
        name
            Name of the namespace.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        await self._namespace.delete(name, wait=True)

    async def delete_pod(self, name: str, namespace: str) -> None:
        """Delete a pod from Kubernetes with a grace period.

        Parameters
        ----------
        name
            Name of the pod.
        namespace
            Namespace of the pod.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        grace_period = LAB_STOP_GRACE_PERIOD
        await self._pod.delete(name, namespace, grace_period=grace_period)

    async def read_secret(self, name: str, namespace: str) -> V1Secret:
        """Read a secret from Kubernetes, failing if it doesn't exist.

        Parameters
        ----------
        name
            Name of the secret.
        namespace
            Namespace of the secret.

        Returns
        -------
        kubernetes_asyncio.client.V1Secret
            Secret object.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        MissingSecretError
            Raised if the secret does not exist.
        """
        secret = await self._secret.read(name, namespace)
        if not secret:
            msg = "Secret does not exist"
            self._logger.error(msg, name=name, namespace=namespace)
            raise MissingSecretError(name, namespace)
        return secret
