"""Kubernetes storage layer for filesystem administration pod."""

from __future__ import annotations

from kubernetes_asyncio.client import ApiClient
from structlog.stdlib import BoundLogger

from ...constants import FSADMIN_NAMESPACE
from ...models.domain.fsadmin import FSAdminObjects
from ...models.domain.kubernetes import PodPhase
from ...timeout import Timeout
from .deleter import PersistentVolumeClaimStorage
from .namespace import NamespaceStorage
from .pod import PodStorage

__all__ = ["FSAdminStorage"]


class FSAdminStorage:
    """Kubernetes storage layer for a filesystem admin pod.

    Parameters
    ----------
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

    def __init__(self, api_client: ApiClient, logger: BoundLogger) -> None:
        self._logger = logger
        self._namespace = NamespaceStorage(api_client, logger)
        self._pod = PodStorage(api_client, logger)
        self._pvc = PersistentVolumeClaimStorage(api_client, logger)

    async def create(self, objects: FSAdminObjects, timeout: Timeout) -> None:
        """Create all of the Kubernetes objects for a fileserver.

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
        MissingObjectError
            Raised if no pod was created for the fsadmin environment.
        TimeoutError
            Raised if the fsadmin namespace or pod takes longer than the
            provided timeout to create or start.

        Notes
        -----
        This is conceptually similar to the fileserver, but since it's a
        cluster-wide singleton, if the objects all exist, that's fine.  We
        don't try to delete and recreate, but just hand back the existing
        fsadmin environment.
        """
        ns = objects.namespace
        existing_ns = await self._namespace.read(ns.metadata.name, timeout)
        if existing_ns is None:
            await self._namespace.create(ns)

        for pvc in objects.pvcs:
            pvcobj = await self._pvc.read(
                ns.metadata.name, pvc.metadata.name, timeout
            )
            if pvcobj is None:
                await self._pvc.create(ns.metadata.name, pvc, timeout)

        pod = objects.pod
        existing_pod = await self._pod.read(
            ns.metadata.name, pod.metadata.name, timeout
        )
        if existing_pod is None:
            await self._pod.create(ns.metadata.name, pod, timeout)

        # Wait for the pod to start.
        await self._pod.wait_for_phase(
            pod.metadata.name,
            ns.metadata.name,
            until_not={PodPhase.UNKNOWN, PodPhase.PENDING},
            timeout=timeout,
        )

    async def delete(self, timeout: Timeout) -> None:
        """Delete the fsadmin environment.

        Parameters
        ----------
        timeout
            Timeout on operation.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        TimeoutError
            Raised if the deletion of any individual object took longer than
            the Kubernetes delete timeout.

        Notes
        -----
        It should be safe to just delete the namespace and let Kubernetes
        do all the cleanup inside it.  Let's try that first.
        """
        await self._namespace.delete(FSADMIN_NAMESPACE)
