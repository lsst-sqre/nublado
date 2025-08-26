"""Kubernetes storage layer for filesystem administration pod."""

from __future__ import annotations

import datetime

from kubernetes_asyncio.client import ApiClient
from safir.datetime import current_datetime, parse_isodatetime
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
        self._start_time = current_datetime(microseconds=True)
        # If get_status() fails, the check will clear _start_time
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
        self._start_time = None
        await self._pod.delete(pod.metadata.name, ns, timeout, wait=True)
        for pvc in pvcs:
            await self._pvc.delete(pvc.metadata.name, ns, timeout, wait=True)

    async def get_status(self, timeout: Timeout) -> FSAdminStatus:
        """Return the status of the fsadmin environment.

        If it is ready for work, return an FSAdminStatus object with
        start_time set to the time the pod went into ``Running`` phase
        and phase set to PodPhase.RUNNING.

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
            self._start_time = None
            raise PodNotFoundError(f"{ns}/{self._config.pod_name}")
        if existing_pod.status.phase != "Running":
            self._start_time = None
            raise InvalidPodPhaseError(existing_pod.status.phase)
        if self._start_time is None:
            # This could happen if the fsadmin pod is running and the
            # controller is restarted.
            #
            # If that should happen...use the pod status start time as
            # the start time.  It's a little too early, but it's fairly
            # close, and the point is, you have a running pod and it's
            # about this old.
            start_time = parse_isodatetime(existing_pod.status.start_time)
            self._logger.warning(
                "No fsadmin start time found; using pod start time"
                f" {start_time} in lieu"
            )
            self._start_time = start_time
        return FSAdminStatus(
            start_time=self._start_time, phase=PodPhase.RUNNING
        )
