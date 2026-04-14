"""Kubernetes storage layer for migrator pod."""

import datetime

from kubernetes_asyncio.client import ApiClient
from structlog.stdlib import BoundLogger

from ...config import FSAdminConfig
from ...models.domain.kubernetes import PodPhase
from ...models.domain.migrator import MigratorObjects
from ...models.v1.migrator import MigratorStatus
from ...timeout import Timeout
from ..metadata import MetadataStorage
from .deleter import PersistentVolumeClaimStorage
from .pod import PodStorage

__all__ = ["MigratorStorage"]


class MigratorStorage:
    """Kubernetes storage layer for a migrator pod.

    Parameters
    ----------
    fsadmin_config
        Configuration for fsadmin environment (used for resources).
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
    This class isn't strictly necessary; instead, the migrator service
    could call the storage layers for individual Kubernetes objects
    directly. Even though there are not many objects, having a wrapper layer
    might be easier to follow.
    """

    def __init__(
        self,
        *,
        fsadmin_config: FSAdminConfig,
        metadata_storage: MetadataStorage,
        api_client: ApiClient,
        reconnect_timeout: datetime.timedelta,
        logger: BoundLogger,
    ) -> None:
        self._fsadmin_config = fsadmin_config
        self._logger = logger
        self._metadata = metadata_storage
        self._pod = PodStorage(api_client, reconnect_timeout, logger)
        self._pvc = PersistentVolumeClaimStorage(
            api_client, reconnect_timeout, logger
        )

    async def create(
        self, objects: MigratorObjects, timeout: Timeout
    ) -> MigratorStatus:
        """Create all of the Kubernetes objects for a migrator instance.

        Create the objects in Kubernetes and then wait for the fsadmin pod
        to start.

        Parameters
        ----------
        objects
            Kubernetes objects making up the fsadmin environment.
        timeout
            How long to wait for the migrator pod to start.

        Returns
        -------
        MigratorStatus
            Pod status.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        TimeoutError
            Raised if migrator is not ready before the timeout expires.
        """
        status = await self.get_status(objects.pod.metadata.name, timeout)
        if status is not None and status.exit_code is None:
            # We have a status and no exit code; therefore, we think the pod
            # is still running, so we just return the extant status
            return status
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
        status = await self.get_status(objects.pod.metadata.name, timeout)
        if status is None:
            # ???
            return MigratorStatus()
        return status

    async def delete(self, objects: MigratorObjects, timeout: Timeout) -> None:
        """Delete the migrator instance.

        Parameters
        ----------
        objects
            Kubernetes objects making up the migrator environment.
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

    async def get_status(
        self, pod_name: str, timeout: Timeout
    ) -> MigratorStatus | None:
        """Return the status of the fsadmin environment.

        Parameters
        ----------
        pod_name
            Name of pod to check.
        timeout
            Timeout on operation.

        Returns
        -------
        MigratorStatus|None
            Pod status.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        TimeoutError
            Raised if fsadmin is not ready before the provided timeout expires.
        """
        ns = self._metadata.namespace
        existing_pod = await self._pod.read(pod_name, ns, timeout)
        if existing_pod is None:
            return None
        status = existing_pod.status
        start_time = status.start_time.isoformat()
        phase = status.phase
        if phase == "Running":
            return MigratorStatus(start_time=start_time)
        # Each pod only has one container.  We hope.
        cses = status.container_statuses
        if len(cses) < 1:
            # Uhhhh.
            return MigratorStatus(
                start_time=start_time,
                end_time=datetime.datetime.now(tz=datetime.UTC).isoformat(),
                exit_code=0,
            )
        cs = cses[0]
        state = cs.state
        if state.running or state.waiting or not state.terminated:
            # Functionally the same as waiting
            return MigratorStatus(start_time=start_time)
        term = cs.state.terminated
        return MigratorStatus(
            start_time=start_time,
            end_time=term.finished_at.isoformat(),
            exit_code=term.exit_code,
        )
