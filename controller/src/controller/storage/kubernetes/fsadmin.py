"""Kubernetes storage layer for filesystem administration pod."""

# As with the fsadmin service, this is very similar to the fileserver, but
# lacks a username.

from __future__ import annotations

from collections.abc import AsyncIterator

from kubernetes_asyncio.client import ApiClient
from structlog.stdlib import BoundLogger

from ...config import FSAdminConfig
from ...models.domain.fsadmin import FSAdminObjects
from ...models.domain.kubernetes import PodChange, PodPhase
from ...timeout import Timeout
from .deleter import PersistentVolumeClaimStorage
from .namespace import NamespaceStorage
from .pod import PodStorage

__all__ = ["FSAdminStorage"]


class FSAdminStorage:
    """Kubernetes storage layer for a filesystem admin pod.

    Parameters
    ----------
    config
        Configuration for fsadmin environment.
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
        self, config: FSAdminConfig, api_client: ApiClient, logger: BoundLogger
    ) -> None:
        self._config = config
        self._logger = logger
        self._namespace = NamespaceStorage(api_client, logger)
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
        ns = objects.namespace
        existing_ns = await self._namespace.read(ns.metadata.name, timeout)
        if existing_ns is None:
            await self._namespace.create(ns, timeout)

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
        """Delete the fsadmin instance.

        Parameters
        ----------
        timeout
            Timeout on operation.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        TimeoutError
            Raised if fsadmin namespace is not deleted within provided timeout.

        Notes
        -----
        It should be safe to just delete the namespace and let Kubernetes
        do all the cleanup inside it. Wait until the namespace has gone
        away before returning.
        """
        await self._namespace.delete(
            self._config.namespace, timeout, wait=True
        )

    async def is_fsadmin_ready(self, timeout: Timeout) -> bool:
        """Check whether the fsadmin environment is ready for work.

        Parameters
        ----------
        timeout
            Timeout on operation.

        Notes
        -----
        This means "does the namespace exist, does the pod in it exist,
        and is the pod in it running?"
        """
        existing_ns = await self._namespace.read(
            self._config.namespace, timeout
        )
        if existing_ns is None:  # No namespace
            return False
        existing_pod = await self._pod.read(
            self._config.namespace, self._config.pod_name, timeout
        )
        if existing_pod is None:  # No pod
            return False
        # Return its running state
        return existing_pod.status.phase == PodPhase.RUNNING

    async def watch_pod(self) -> AsyncIterator[PodChange]:
        """Watches the fsadmin namespace for pod phase changes.

        Technically, this iterator detects any change to a pod and returns its
        current phase. The change may not be a phase change. That's good
        enough for our purposes.

        It will continue forever until cancelled. It is meant to be run from a
        background task handling fsadmin pod phase changes.

        Yields
        ------
        PodChange
            Phase change of a pod in this namespace.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        async for change in self._pod.watch_pod_changes(
            self._config.namespace
        ):
            yield change
