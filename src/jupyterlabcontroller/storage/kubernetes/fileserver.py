"""Kubernetes storage layer for user fileservers."""

from __future__ import annotations

from datetime import timedelta

from kubernetes_asyncio.client import ApiClient, V1Pod
from safir.datetime import current_datetime
from structlog.stdlib import BoundLogger

from ...exceptions import DuplicateObjectError, MissingObjectError
from ...models.domain.fileserver import FileserverObjects
from ...models.domain.kubernetes import PodPhase
from .custom import GafaelfawrIngressStorage
from .deleter import JobStorage, ServiceStorage
from .ingress import IngressStorage
from .pod import PodStorage

__all__ = ["FileserverStorage"]


class FileserverStorage:
    """Kubernetes storage layer for fileservers.

    Parameters
    ----------
    api_client
        Kubernetes API client.
    logger
        Logger to use.

    Notes
    -----
    This class isn't strictly necessary; instead, the fileserver service could
    call the storage layers for individual Kubernetes objects directly. But
    there are enough different objects in play that adding a thin layer to
    wrangle the storage objects makes the fileserver service easier to follow.
    """

    def __init__(self, api_client: ApiClient, logger: BoundLogger) -> None:
        self._logger = logger
        self._gafaelfawr = GafaelfawrIngressStorage(api_client, logger)
        self._ingress = IngressStorage(api_client, logger)
        self._job = JobStorage(api_client, logger)
        self._service = ServiceStorage(api_client, logger)
        self._pod = PodStorage(api_client, logger)

    async def create(
        self, namespace: str, objects: FileserverObjects, timeout: timedelta
    ) -> None:
        """Create all of the Kubernetes objects for a fileserver.

        Create the objects in Kubernetes and then wait for the fileserver pod
        to start and for the ingress to be ready.

        Parameters
        ----------
        namespace
            Namespace where the objects should live.
        objects
            Kubernetes objects making up the fileserver.
        timeout
            How long to wait for the fileserver to start.

        Raises
        ------
        DuplicateObjectError
            Raised if multiple pods were found for the fileserver job.
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        MissingObjectError
            Raised if no pod was created for the fileserver job.
        TimeoutError
            Raised if the fileserver takes longer than the provided timeout to
            create or start.
        """
        start = current_datetime(microseconds=True)
        await self._gafaelfawr.create(namespace, objects.ingress)
        await self._service.create(namespace, objects.service)
        await self._job.create(namespace, objects.job)

        # Wait for the pod to start.
        pod = await self._get_pod_for_job(objects.job.metadata.name, namespace)
        timeout_left = timeout - (current_datetime(microseconds=True) - start)
        if timeout_left <= timedelta(seconds=0):
            raise TimeoutError
        await self._pod.wait_for_phase(
            pod.metadata.name,
            namespace,
            until_not={PodPhase.UNKNOWN, PodPhase.PENDING},
            timeout=timeout_left,
        )

        # Wait for the ingress to get an IP address assigned. This usually
        # takes the longest.
        name = objects.ingress["metadata"]["name"]
        timeout_left = timeout - (current_datetime(microseconds=True) - start)
        if timeout_left <= timedelta(seconds=0):
            raise TimeoutError
        await self._ingress.wait_for_ip_address(name, namespace, timeout_left)

    async def delete(self, name: str, namespace: str) -> None:
        """Delete a fileserver.

        Parameters
        ----------
        name
            Name of the filesever objects.
        namespace
            Namespace in which fileservers run.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        await self._gafaelfawr.delete(name, namespace, wait=True)
        await self._ingress.wait_for_deletion(name, namespace)
        await self._service.delete(name, namespace)
        await self._job.delete(name, namespace, wait=True)

    async def wait_for_pod_exit(self, name: str, namespace: str) -> None:
        """Wait for the fileserver pod spawned by the job to exit.

        Parameters
        ----------
        name
            Name of the fileserver job.
        namespace
            Namespace in which fileservers run.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        pod = await self._get_pod_for_job(name, namespace)
        await self._pod.wait_for_phase(
            pod.metadata.name,
            namespace,
            until_not={PodPhase.UNKNOWN, PodPhase.PENDING, PodPhase.RUNNING},
        )

    async def _get_pod_for_job(self, name: str, namespace: str) -> V1Pod:
        """Get the ``Pod`` corresponding to a ``Job``.

        Parameters
        ----------
        name
            Name of the job.
        namespace
            Namespace in which to search.

        Returns
        -------
        kubernetes_asyncio.client.V1Pod
            Corresponding pod.

        Raises
        ------
        DuplicateObjectError
            Raised if multiple pods were found for the fileserver job.
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        MissingObjectError
            Raised if no pod was created for the fileserver job.
        """
        selector = f"job-name={name}"
        pods = await self._pod.list(namespace, label_selector=selector)
        if not pods:
            raise MissingObjectError(
                message=f"Pod for fileserver job {name} not found",
                namespace=namespace,
                kind="Pod",
            )
        if len(pods) > 1:
            msg = f"Multiple pods match job {name}"
            raise DuplicateObjectError(msg, kind="Pod", namespace=namespace)
        return pods[0]
