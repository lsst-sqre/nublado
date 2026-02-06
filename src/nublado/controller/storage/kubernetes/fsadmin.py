"""Kubernetes storage layer for filesystem administration pod."""

from __future__ import annotations

from datetime import timedelta

from kubernetes_asyncio.client import ApiClient
from structlog.stdlib import BoundLogger

from ...config import FSAdminConfig
from ...exceptions import InvalidPodPhaseError, PodNotFoundError
from ...models.domain.fsadmin import FSAdminObjects
from ...models.domain.kubernetes import PodPhase
from ...models.v1.fsadmin import FSAdminStatus
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
    reconnect_timeout
        How long to wait before explictly restarting Kubernetes watches. This
        can prevent the connection from getting unexpectedly getting closed,
        resulting in 400 errors, or worse, events silently stopping.
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
        reconnect_timeout: timedelta,
        logger: BoundLogger,
    ) -> None:
        self._config = config
        self._logger = logger
        self._metadata = metadata_storage
        self._pod = PodStorage(api_client, reconnect_timeout, logger)
        self._pvc = PersistentVolumeClaimStorage(
            api_client, reconnect_timeout, logger
        )

    async def create(
        self, objects: FSAdminObjects, timeout: Timeout
    ) -> FSAdminStatus:
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
        FSAdminStatus
            Pod status.

        Raises
        ------
        InvalidPodPhaseError
            Pod is not in ``Running`` phase.
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        PodNotFoundError
            Pod does not exist.
        TimeoutError
            Raised if fsadmin is not ready before the provided timeout expires.
        """
        ns = self._metadata.namespace
        for pvc in objects.pvcs:
            await self._pvc.create(ns, pvc, timeout, replace=True)
        await self._pod.create(ns, objects.pod, timeout, replace=True)

        # Wait for the pod to start.
        await self._pod.wait_for_phase(
            objects.pod.metadata.name,
            ns,
            until_not={PodPhase.UNKNOWN, PodPhase.PENDING},
            timeout=timeout,
        )
        return await self.get_status(timeout)

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
        await self._pod.delete(pod.metadata.name, ns, timeout, wait=True)
        for pvc in pvcs:
            await self._pvc.delete(pvc.metadata.name, ns, timeout, wait=True)

    async def get_status(self, timeout: Timeout) -> FSAdminStatus:
        """Return the status of the fsadmin environment.

        If it is ready for work, return an FSAdminStatus object with
        start_time set to the time the pod was created and phase set to
        PodPhase.RUNNING.

        Otherwise raise an exception: either the pod is missing, or the
        pod is not in ``Running`` phase.

        Parameters
        ----------
        timeout
            Timeout on operation.

        Returns
        -------
        FSAdminStatus
            Pod status if ready.

        Raises
        ------
        InvalidPodPhaseError
            Pod is not in ``Running`` phase.
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        PodNotFoundError
            Pod does not exist.
        TimeoutError
            Raised if fsadmin is not ready before the provided timeout expires.
        """
        ns = self._metadata.namespace
        existing_pod = await self._pod.read(self._config.pod_name, ns, timeout)
        if existing_pod is None:
            raise PodNotFoundError(f"{ns}/{self._config.pod_name}")
        if existing_pod.status.phase != "Running":
            raise InvalidPodPhaseError(existing_pod.status.phase)
        return FSAdminStatus(start_time=existing_pod.status.start_time)
