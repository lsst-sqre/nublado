"""Storage layer for ``Pod`` objects."""

from collections.abc import AsyncIterator
from datetime import timedelta

from kubernetes_asyncio import client
from kubernetes_asyncio.client import ApiClient, CoreV1Event, V1Pod
from structlog.stdlib import BoundLogger

from ...exceptions import ControllerTimeoutError
from ...models.domain.kubernetes import PodChange, PodPhase, WatchEventType
from ...timeout import Timeout
from .deleter import KubernetesObjectDeleter
from .watcher import KubernetesWatcher

__all__ = ["PodStorage"]


class PodStorage(KubernetesObjectDeleter[V1Pod]):
    """Storage layer for ``Pod`` objects.

    Parameters
    ----------
    api_client
        Kubernetes API client.
    reconnect_timeout
        How long to wait before explictly restarting Kubernetes watches. This
        can prevent the connection from getting unexpectedly getting closed,
        resulting in 400 errors, or worse, events silently stopping.
    logger
        Logger to use.
    """

    def __init__(
        self,
        api_client: ApiClient,
        reconnect_timeout: timedelta,
        logger: BoundLogger,
    ) -> None:
        self._api = client.CoreV1Api(api_client)
        super().__init__(
            create_method=self._api.create_namespaced_pod,
            delete_method=self._api.delete_namespaced_pod,
            list_method=self._api.list_namespaced_pod,
            read_method=self._api.read_namespaced_pod,
            object_type=V1Pod,
            kind="Pod",
            reconnect_timeout=reconnect_timeout,
            logger=logger,
        )

    async def delete_after_completion(
        self, name: str, namespace: str, timeout: Timeout
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
            How long to wait for the pod to start and then stop.

        Raises
        ------
        ControllerTimeoutError
            Raised if the timeout expires while waiting for a pod phase
            change.
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        TimeoutError
            Raised if the timeout expires while performing Kubernetes
            operations.
        """
        logger = self._logger.bind(name=name, namespace=namespace)
        phase = await self.wait_for_phase(
            name,
            namespace,
            until_not={PodPhase.UNKNOWN, PodPhase.PENDING, PodPhase.RUNNING},
            timeout=timeout,
        )
        if phase is None:
            logger.warning("Pod was already missing")
            return
        if phase == PodPhase.SUCCEEDED:
            logger.debug("Removing succeeded pod")
        else:
            logger.warning(f"Removing pod in phase {phase.value}")
        await self.delete(name, namespace, timeout)

    async def events_for_pod(
        self, name: str, namespace: str, timeout: Timeout
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
        timeout
            How long to watch events for. When this timeout expires, the
            iterator will end without raising any error.

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
            timeout=timeout,
            reconnect_timeout=self._reconnect_timeout,
            logger=logger,
        )
        try:
            async with timeout.enforce():
                async for event in watcher.watch():
                    yield event.object.message
        except ControllerTimeoutError:
            pass
        finally:
            await watcher.close()

    async def wait_for_phase(
        self,
        name: str,
        namespace: str,
        timeout: Timeout,
        *,
        until_not: set[PodPhase],
    ) -> PodPhase | None:
        """Wait for a pod to exit a set of phases.

        Waits for the pod to reach a phase other than the ones given, and
        returns the new phase.

        Parameters
        ----------
        pod_name
            Name of the pod.
        namespace
            Namespace in which the pod is located.
        timeout
            Timeout to wait for the pod to enter another phase.
        until_not
            Wait until the pod is not in one of these phases (or was deleted,
            or the watch timed out).

        Returns
        -------
        PodPhase
            New pod phase, or `None` if the pod has disappeared.

        Raises
        ------
        ControllerTimeoutError
            Raised if the timeout expires.
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        TimeoutError
            Raised if the timeout expires while getting the starting pod
            phase.
        """
        logger = self._logger.bind(name=name, namespace=namespace)
        logger.debug(
            "Waiting for pod phase change",
            until_not=[p.value for p in until_not],
        )

        # Retrieve the object first. It's possible that it's already in the
        # correct phase, and we can return immediately. If not, we want to
        # start watching events with the next event after the current object
        # version. Note that we treat Unknown the same as Pending; we rely on
        # the timeout and otherwise hope that Kubernetes will figure out the
        # phase.
        pod = await self.read(name, namespace, timeout)
        if pod is None:
            return None
        phase = PodPhase(pod.status.phase)
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
            reconnect_timeout=self._reconnect_timeout,
            logger=logger,
        )
        try:
            async with timeout.enforce():
                async for event in watcher.watch():
                    if event.action == WatchEventType.DELETED:
                        return None
                    phase = PodPhase(event.object.status.phase)
                    if phase not in until_not:
                        logger.debug("Pod phase changed", status=phase.value)
                        return phase
        finally:
            await watcher.close()

        # This should be impossible; someone called stop on the watcher.
        raise RuntimeError("Wait for pod phase change unexpectedly stopped")

    async def watch_pod_changes(
        self, namespace: str
    ) -> AsyncIterator[PodChange]:
        """Watches a namespace for pod changes (not creation or deletion).

        This watch will continue forever until cancelled. It is meant to be
        run from a background task handling pod changes continuously.

        Parameters
        ----------
        namespace
            Namespace to watch for changes.

        Yields
        ------
        PodChange
            Change to a pod in this namespace.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        logger = self._logger.bind(namespace=namespace)
        logger.debug("Waiting for pod changes")
        watcher = KubernetesWatcher(
            method=self._list,
            object_type=V1Pod,
            kind="Pod",
            namespace=namespace,
            timeout=None,
            reconnect_timeout=self._reconnect_timeout,
            logger=logger,
        )
        try:
            while True:
                async for event in watcher.watch():
                    if event.action != WatchEventType.MODIFIED:
                        continue
                    phase = PodPhase(event.object.status.phase)
                    logger.debug(
                        "Saw modified pod",
                        name=event.object.metadata.name,
                        phase=phase.value,
                    )
                    yield PodChange(pod=event.object, phase=phase)
        finally:
            await watcher.close()
