"""Kubernetes storage layer for filesystem administration pod."""

# As with the fsadmin service, this is very similar to the fileserver, but
# lacks a username.

from __future__ import annotations

import datetime

from kubernetes_asyncio.client import ApiClient
from safir.datetime import current_datetime
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
        *,
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
        self._start_time: datetime.datetime | None = None

    async def create(
        self, objects: FSAdminObjects, timeout: Timeout
    ) -> datetime.datetime:
        """Create all of the Kubernetes objects for an fsadmin instance.

        Create the objects in Kubernetes and then wait for the fsadmin pod
        to start.

        Returns the time at which the pod went into Running phase.

        Parameters
        ----------
        objects
            Kubernetes objects making up the fsadmin environment.
        timeout
            How long to wait for the fsadmin pod to start.

        Returns
        -------
        datetime.datetime

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
            await self._pvc.create(ns, pvc, timeout)
        await self._pod.create(ns, objects.pod, timeout)

        # Wait for the pod to start.
        await self._pod.wait_for_phase(
            objects.pod.metadata.name,
            ns,
            until_not={PodPhase.UNKNOWN, PodPhase.PENDING},
            timeout=timeout,
        )
        self._start_time = current_datetime(microseconds=True)
        return self._start_time

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
            Raised if fsadmin objects are not deleted within provided timeout.
        """
        ns = self._metadata.namespace
        pod = objects.pod
        pvcs = objects.pvcs
        self._start_time = None
        await self._pod.delete(pod.metadata.name, ns, timeout, wait=True)
        for pvc in pvcs:
            await self._pvc.delete(pvc.metadata.name, ns, timeout)

    async def is_fsadmin_ready(self, timeout: Timeout) -> bool:
        """Check whether the fsadmin environment is ready for work.

        Parameters
        ----------
        timeout
            Timeout on operation.

        Returns
        -------
        bool
            Whether the fsadmin pod is ready.

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
        # Return whether it is running
        return existing_pod.status.phase == PodPhase.RUNNING

    async def get_start_time(
        self, timeout: Timeout
    ) -> datetime.datetime | None:
        """Get time pod started, or None if it is not ready for work.

        Parameters
        ----------
        timeout
            How long to wait to query the fsadmin pod.

        Returns
        -------
        datetime.datetime
            The time the fsadmin pod went into ``Running`` phase.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        TimeoutError
            Raised if fsadmin is not ready before the provided timeout expires.

        Notes
        -----
        If the pod exists but is not yet running, or is in the process of
        terminating, we report None. The start time is only valid for pods
        which are ready to accept work.
        """
        if not await self.is_fsadmin_ready(timeout):
            return None
        return self._start_time
