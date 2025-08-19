"""Kubernetes storage layer for filesystem administration pod."""

# As with the fsadmin service, this is very similar to the fileserver, but
# lacks a username.

from __future__ import annotations

from kubernetes_asyncio.client import ApiClient
from structlog.stdlib import BoundLogger

from ...config import FSAdminConfig
from ...models.domain.fsadmin import FSAdminObjects
from ...models.domain.kubernetes import PodPhase
from ...timeout import Timeout
from ..metadata import MetadataStorage
from .deleter import PersistentVolumeClaimStorage
from .pod import PodStorage

__all__ = ["FSAdminStorage"]


class FSAdminStorage:
    """Kubernetes storage layer for a filesystem admin pod.

    Parameters
    ----------
    config
        Configuration for fsadmin environment.
    metadata_storage
        Holds namespace information.
    api_client
        Kubernetes API client.
    logger
        Logger to use.

    Notes
    -----
    This class isn't strictly necessary; instead, the fsadmin service
    could call the storage layers for individual Kubernetes objects
    directly. Even though there are not many objects, having a wrapper layer
    might be easier to follow.
    """

    def __init__(
        self,
        config: FSAdminConfig,
        metadata_storage: MetadataStorage,
        api_client: ApiClient,
        logger: BoundLogger,
    ) -> None:
        self._config = config
        self._logger = logger
        self._metadata = metadata_storage
        self._pod = PodStorage(api_client, logger)
        self._pvc = PersistentVolumeClaimStorage(api_client, logger)

    async def create(self, objects: FSAdminObjects, timeout: Timeout) -> None:
        """Create all of the Kubernetes objects for an fsadmin instance.

        Create the objects in Kubernetes and then wait for the fsadmin pod
        to start.

        Parameters
        ----------
        objects
            Kubernetes objects making up the fsadmin environment.
        timeout
            How long to wait for the fsadmin pod to start.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        TimeoutError
            Raised if fsadmin is not ready before the provided timeout expires.

        Notes
        -----
        This is conceptually similar to the fileserver, but since it's a
        cluster-wide singleton, if the objects all exist, that's fine.  We
        don't try to delete and recreate, but use the existing fsadmin
        instance.
        """
        ns = self._metadata.namespace
        for pvc in objects.pvcs:
            pvcobj = await self._pvc.read(pvc.metadata.name, ns, timeout)
            if pvcobj is None:
                await self._pvc.create(ns, pvc, timeout)

        pod = objects.pod
        existing_pod = await self._pod.read(pod.metadata.name, ns, timeout)
        if existing_pod is None:
            await self._pod.create(ns, pod, timeout)

        # Wait for the pod to start.
        await self._pod.wait_for_phase(
            pod.metadata.name,
            ns,
            until_not={PodPhase.UNKNOWN, PodPhase.PENDING},
            timeout=timeout,
        )

    async def delete(self, objects: FSAdminObjects, timeout: Timeout) -> None:
        """Delete the fsadmin instance.

        Parameters
        ----------
        objects
            Kubernetes objects making up the fsadmin environment.
        timeout
            Timeout on operation.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        TimeoutError
            Raised if fsadmin namespace is not deleted within provided timeout.
        """
        ns = self._metadata.namespace
        pod = objects.pod
        pvcs = objects.pvcs
        existing_pod = await self._pod.read(pod.metadata.name, ns, timeout)
        if existing_pod is not None:
            await self._pod.delete(
                existing_pod.metadata.name, ns, timeout, wait=True
            )
        for pvc in pvcs:
            if await self._pvc.read(pvc.metadata.name, ns, timeout) is None:
                continue
            await self._pvc.delete(pvc.metadata.name, ns, timeout)

    async def is_fsadmin_ready(self, timeout: Timeout) -> bool:
        """Check whether the fsadmin environment is ready for work.

        Parameters
        ----------
        timeout
            Timeout on operation.

        Notes
        -----
        We check whether the pod exists, and if so, whether it is running.
        We do not need to check the PVCs, because if they're necessary,
        the pod can't be running unless it has them.
        """
        ns = self._metadata.namespace
        existing_pod = await self._pod.read(self._config.pod_name, ns, timeout)
        if existing_pod is None:  # No pod
            return False
        # Return its running state
        return existing_pod.status.phase == PodPhase.RUNNING
