"""Storage layer for ``Pod`` objects."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta

from kubernetes_asyncio import client
from kubernetes_asyncio.client import ApiClient, CoreV1Event, V1Pod
from structlog.stdlib import BoundLogger

from ...models.domain.kubernetes import KubernetesPodPhase, WatchEventType
from .deleter import KubernetesObjectDeleter
from .watcher import KubernetesWatcher

__all__ = ["PodStorage"]


class PodStorage(KubernetesObjectDeleter):
    """Storage layer for ``Pod`` objects.

    Parameters
    ----------
    api_client
        Kubernetes API client.
    logger
        Logger to use.
    """

    def __init__(self, api_client: ApiClient, logger: BoundLogger) -> None:
        self._api = client.CoreV1Api(api_client)
        super().__init__(
            create_method=self._api.create_namespaced_pod,
            delete_method=self._api.delete_namespaced_pod,
            list_method=self._api.list_namespaced_pod,
            read_method=self._api.read_namespaced_pod,
            object_type=V1Pod,
            kind="Pod",
            logger=logger,
        )

    async def delete_after_completion(
        self, name: str, namespace: str, *, timeout: timedelta | None = None
    ) -> None:
        """Wait for a pod to complete and then delete it.

        This first waits for a pod to finish running, after which it deletes
        the pod. This method does not wait for the pod to be deleted before
        returning.

        Parameters
        ----------
        name
            Name of the pod.
        namespace
            Namespace of the pod.
        timeout
            How long to wait for the pod to start and then stop.  This timeout
            is not applied to the deletion.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        logger = self._logger.bind(name=name, namespace=namespace)
        phase = await self.wait_for_phase(
            name,
            namespace,
            until_not={
                KubernetesPodPhase.UNKNOWN,
                KubernetesPodPhase.PENDING,
                KubernetesPodPhase.RUNNING,
            },
            timeout=timeout,
        )
        if phase is None:
            logger.warning("Pod was already missing")
            return
        if phase == KubernetesPodPhase.SUCCEEDED:
            logger.debug("Removing succeeded pod")
        else:
            logger.warning(f"Removing pod in phase {phase.value}")
        await self.delete(name, namespace)

    async def events_for_pod(
        self, name: str, namespace: str
    ) -> AsyncIterator[str]:
        """Iterate over Kubernetes events involving a pod.

        Watches for events involving a pod, yielding them. Must be cancelled
        by the caller when the watch is no longer of interest.

        Parameters
        ----------
        name
            Name of the pod.
        namespace
            Namespace in which the pod is located.

        Yields
        ------
        str
            The next observed event.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        logger = self._logger.bind(pod=name, namespace=namespace)
        logger.debug("Watching pod events")
        watcher = KubernetesWatcher(
            method=self._api.list_namespaced_event,
            object_type=CoreV1Event,
            kind="Event",
            involved_object=name,
            namespace=namespace,
            logger=logger,
        )
        try:
            async for event in watcher.watch():
                yield event.object.message
        finally:
            await watcher.close()

        # This should be impossible; someone called stop on the watcher.
        raise RuntimeError("Wait for pod events unexpectedly stopped")

    async def wait_for_phase(
        self,
        name: str,
        namespace: str,
        *,
        until_not: set[KubernetesPodPhase],
        timeout: timedelta | None = None,
    ) -> KubernetesPodPhase | None:
        """Waits for a pod to finish starting.

        Waits for the pod to reach a phase other than the ones given, and
        returns the new phase.

        Parameters
        ----------
        pod_name
            Name of the pod.
        namespace
            Namespace in which the pod is located.
        until_not
            Wait until the pod is not in one of these phases (or was deleted,
            or the watch timed out).
        timeout
            Timeout to wait for the pod to start.

        Returns
        -------
        KubernetesPodPhase
            New pod phase, or `None` if the pod has disappeared.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        logger = self._logger.bind(name=name, namespace=namespace)
        logger.debug("Waiting for pod phase change", until_not=list(until_not))

        # Retrieve the object first. It's possible that it's already in the
        # correct phase, and we can return immediately. If not, we want to
        # start watching events with the next event after the current object
        # version. Note that we treat Unknown the same as Pending; we rely on
        # the timeout and otherwise hope that Kubernetes will figure out the
        # phase.
        pod = await self.read(name, namespace)
        if pod is None:
            return None
        phase = KubernetesPodPhase(pod.status.phase)
        if phase not in until_not:
            return phase

        # The pod is not in a terminal phase. Start the watch and wait for it
        # to change state.
        watcher = KubernetesWatcher(
            method=self._list,
            object_type=V1Pod,
            kind="Pod",
            name=pod.metadata.name,
            namespace=pod.metadata.namespace,
            resource_version=pod.metadata.resource_version,
            timeout=timeout,
            logger=logger,
        )
        try:
            async for event in watcher.watch():
                if event.action == WatchEventType.DELETED:
                    return None
                phase = KubernetesPodPhase(event.object.status.phase)
                if phase not in until_not:
                    return phase
        finally:
            await watcher.close()

        # This should be impossible; someone called stop on the watcher.
        raise RuntimeError("Wait for pod phase change unexpectedly stopped")
