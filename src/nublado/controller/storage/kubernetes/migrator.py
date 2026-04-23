"""Kubernetes storage layer for migrator pod."""

import asyncio
import datetime

from kubernetes_asyncio.client import ApiClient
from structlog.stdlib import BoundLogger

from ...exceptions import MigratorConflictError
from ...models.domain.kubernetes import PodPhase
from ...models.domain.migrator import MigratorObjects, build_migrator_pod_name
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

    Create, delete, and get_status will all be called with the service
    manager's lock asserted.  They are not concurrency-safe.

    The lock in here is used to control access to the cache; the cache only
    tracks exited (and then cleaned-up) pods, not pods in progress.
    """

    def __init__(
        self,
        *,
        metadata_storage: MetadataStorage,
        api_client: ApiClient,
        reconnect_timeout: datetime.timedelta,
        logger: BoundLogger,
    ) -> None:
        self._logger = logger
        self._metadata = metadata_storage
        self._pod = PodStorage(api_client, reconnect_timeout, logger)
        self._pvc = PersistentVolumeClaimStorage(
            api_client, reconnect_timeout, logger
        )
        # Cache holds status for completed pods only, so that we can delete
        # the pod once we have read its status.
        self._cache: dict[str, MigratorStatus] = {}
        self._lock = asyncio.Lock()

    def _check_object_names(
        self, old_user: str, new_user: str, objects: MigratorObjects
    ) -> None:
        pod_name = build_migrator_pod_name(old_user, new_user)
        if pod_name != objects.pod.metadata.name:
            # Sanity check, should never happen.
            raise RuntimeError(
                f"Calculated pod name {pod_name} did not match requested"
                f" pod name {objects.pod.metadata.name}"
            )
        for pvc in objects.pvcs:
            if not pvc.metadata.name.startswith(pod_name):
                raise RuntimeError(
                    f"PVC name {pvc.metadata.name} did not start"
                    f" with {pod_name}"
                )

    async def create(
        self,
        old_user: str,
        new_user: str,
        objects: MigratorObjects,
        timeout: Timeout,
    ) -> MigratorStatus:
        """Create all of the Kubernetes objects for a migrator instance.

        Create the objects in Kubernetes and then wait for the migrator pod
        to start.

        Parameters
        ----------
        old_user
            Username for source user to copy from.
        new_user
            Username for target user to copy to.
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
        self._check_object_names(old_user, new_user, objects)
        pod_name = build_migrator_pod_name(old_user, new_user)
        status = await self.get_status(old_user, new_user, objects, timeout)
        if status is not None and status.running:
            # The pod is still running, so we just return that.
            return status
        # Check for existence of a migration going the other way.
        # Note that by passing None as its object set, no cleanup
        # will be attempted, which is what we want, since that migration
        # is only our business insofar as we don't want to be copying A to
        # B and B to A at the same time.
        reverse_status = await self.get_status(
            new_user, old_user, None, timeout
        )
        if reverse_status and reverse_status.running:
            raise MigratorConflictError(
                f"Migration for {new_user} -> {old_user} already in progress"
            )
        # Clear the pod from the cache.
        if pod_name in self._cache:
            async with self._lock:
                del self._cache[pod_name]
        # Create the objects (recreating if needed).
        ns = self._metadata.namespace
        for pvc in objects.pvcs:
            await self._pvc.create(ns, pvc, timeout, replace=True)
        await self._pod.create(ns, objects.pod, timeout, replace=True)

        # Wait for the pod to start.
        await self._pod.wait_for_phase(
            pod_name,
            ns,
            until_not={PodPhase.UNKNOWN, PodPhase.PENDING},
            timeout=timeout,
        )
        st = await self.get_status(old_user, new_user, objects, timeout)
        if st is None:  # This really should never happen.
            raise RuntimeError(
                f"Status for {old_user} -> {new_user} migration is None"
            )
        return st

    async def delete(
        self,
        old_user: str,
        new_user: str,
        objects: MigratorObjects,
        timeout: Timeout,
    ) -> None:
        """Delete the migrator instance.  Leave any of its information in the
        cache.

        Parameters
        ----------
        old_user
            Username for source user to copy from.
        new_user
            Username for target user to copy to.
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
        self._check_object_names(old_user, new_user, objects)
        ns = self._metadata.namespace
        pod = objects.pod
        pvcs = objects.pvcs
        await self._pod.delete(pod.metadata.name, ns, timeout, wait=True)
        for pvc in pvcs:
            await self._pvc.delete(pvc.metadata.name, ns, timeout, wait=True)

    async def get_status(
        self,
        old_user: str,
        new_user: str,
        objects: MigratorObjects | None,
        timeout: Timeout,
        *,
        clean: bool = True,
    ) -> MigratorStatus | None:
        """Return the status of the migrator environment for a particular
        user pair, or None if there has been no migration attempt.

        Parameters
        ----------
        old_user
            Name of source user to copy from.
        new_user
            Name of target user to copy to.
        timeout
            Timeout on operation.

        Returns
        -------
        MigratorStatus
            Pod status.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        TimeoutError
            Raised if fsadmin is not ready before the provided timeout expires.
        """
        ns = self._metadata.namespace
        pod_name = build_migrator_pod_name(old_user, new_user)
        existing_pod = await self._pod.read(pod_name, ns, timeout)
        if existing_pod is None:
            async with self._lock:
                return self._cache.get(pod_name)  # Possibly None
        status = existing_pod.status
        start_time = status.start_time.isoformat()
        phase = status.phase
        if phase == "Running":
            # Do not put running pods into cache
            return MigratorStatus(
                old_user=old_user,
                new_user=new_user,
                start_time=start_time,
                running=True,
            )
        # Each pod only has one container.  We hope.
        cses = status.container_statuses
        if len(cses) < 1:
            # Uhhhh.  This shouldn't happen, but if it does, we don't know
            # anything about the pod, so return None.
            return None
        cs = cses[0]  # We assume a single container.
        state = cs.state
        if state.running or state.waiting or not state.terminated:
            # Functionally the same as waiting
            ms = MigratorStatus(
                old_user=old_user,
                new_user=new_user,
                start_time=start_time,
                running=True,
            )
        else:
            term = cs.state.terminated
            ms = MigratorStatus(
                old_user=old_user,
                new_user=new_user,
                start_time=start_time,
                end_time=term.finished_at.isoformat(),
                running=False,
                exit_code=term.exit_code,
            )
        # Store the status in the cache.
        async with self._lock:
            self._cache[pod_name] = ms
        # Clean up the pod from Kubernetes, leaving the cached status, if
        # we were called with the objects to allow us to do that. (We will
        # not be when we are checking for the reverse migrator.)
        if objects is not None:
            await self.delete(old_user, new_user, objects, timeout)
        return ms
