"""Kubernetes storage layer for user labs."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta

from kubernetes_asyncio.client import ApiClient, V1Secret
from structlog.stdlib import BoundLogger

from ...constants import LAB_STOP_GRACE_PERIOD
from ...exceptions import MissingSecretError
from ...models.domain.kubernetes import PodPhase
from ...models.domain.lab import LabObjectNames, LabObjects, LabStateObjects
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
        await self._config_map.create(namespace, objects.env_config_map)
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

    async def delete_pod(self, names: LabObjectNames) -> None:
        """Delete a pod from Kubernetes with a grace period.

        Parameters
        ----------
        names
            Names of lab objects.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        grace_period = LAB_STOP_GRACE_PERIOD
        namespace = names.namespace
        await self._pod.delete(names.pod, namespace, grace_period=grace_period)

    async def list_namespaces(self, prefix: str) -> list[str]:
        """List all namespaces starting with the given prefix.

        Used to discover all namespaces for running user labs when doing state
        reconciliation.

        Parameters
        ----------
        prefix
            String prefix of namespaces to return.

        Returns
        -------
        list of str
            List of namespace names.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        namespaces = await self._namespace.list()
        return [
            n.metadata.name
            for n in namespaces
            if n.metadata.name.startswith(prefix)
        ]

    async def read_lab_objects(
        self, names: LabObjectNames
    ) -> LabStateObjects | None:
        """Read the lab objects required to reconstruct state.

        Used during reconciliation to rebuild the internal mental model of the
        current state of a user's lab.

        Parameters
        ----------
        names
            Names of the user's lab objects, usually generated by
            `~jupyterlabcontroller.services.builder.lab.LabBuilder`.

        Returns
        -------
        LabStateObjects or None
            Lab objects required to reconstruct state, or `None` if any of the
            required objects were missing.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        logger = self._logger.bind(user=names.username)
        namespace = names.namespace
        env_map = await self._config_map.read(names.env_config_map, namespace)
        if not env_map:
            logger.warning("User ConfigMap missing", name=names.env_config_map)
            return None
        pod = await self._pod.read(names.pod, namespace)
        if not pod:
            logger.warning("User Pod missing", name=names.pod)
            return None
        quota = await self._quota.read(names.quota, namespace)
        return LabStateObjects(env_config_map=env_map, quota=quota, pod=pod)

    async def read_pod_phase(self, names: LabObjectNames) -> PodPhase | None:
        """Get the phase of a running user lab pod.

        Called whenever JupyterHub wants to check the status of running pods,
        so this will be called frequently and should be fairly quick.

        Parameters
        ----------
        names
            Names of the user's lab objects, usually generated by
            `~jupyterlabcontroller.services.builder.lab.LabBuilder`.

        Returns
        -------
        PodPhase or None
            Phase of the pod or `None` if the pod does not exist.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        pod = await self._pod.read(names.pod, names.namespace)
        if pod is None:
            return None
        msg = f"Pod phase is {pod.status.phase}"
        self._logger.debug(msg, name=names.pod, namespace=names.namespace)
        return PodPhase(pod.status.phase)

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

    async def wait_for_pod_start(
        self, names: LabObjectNames, timeout: timedelta
    ) -> PodPhase | None:
        """Waits for a pod to finish starting.

        Waits for the pod to reach a phase other than pending or unknown, and
        returns the new phase. We treat unknown like pending since we're
        running with a timeout anyway, and will eventually time out if we
        can't get back access to the node where the pod is running.

        Parameters
        ----------
        names
            Names for lab objects.
        timeout
            Timeout to wait for the pod to start.

        Returns
        -------
        PodPhase
            New pod phase, or `None` if the pod has disappeared.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        return await self._pod.wait_for_phase(
            names.pod,
            names.namespace,
            until_not={PodPhase.UNKNOWN, PodPhase.PENDING},
            timeout=timeout,
        )

    async def watch_pod_events(
        self, names: LabObjectNames
    ) -> AsyncIterator[str]:
        """Monitor the startup of a pod.

        Watches for events involving a pod, yielding them. Must be cancelled
        by the caller when the watch is no longer of interest.

        Parameters
        ----------
        names
            Lab object names.

        Yields
        ------
        str
            The next observed event.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        namespace = names.namespace
        async for message in self._pod.events_for_pod(names.pod, namespace):
            yield message
