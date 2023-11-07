"""Kubernetes storage layer for user fileservers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta

from kubernetes_asyncio.client import ApiClient, V1Pod
from safir.datetime import current_datetime
from structlog.stdlib import BoundLogger

from ...exceptions import DuplicateObjectError, MissingObjectError
from ...models.domain.fileserver import (
    FileserverObjects,
    FileserverStateObjects,
)
from ...models.domain.kubernetes import PodChange, PodPhase
from .custom import GafaelfawrIngressStorage
from .deleter import JobStorage, ServiceStorage
from .ingress import IngressStorage
from .namespace import NamespaceStorage
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
        self._namespace = NamespaceStorage(api_client, logger)
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
        await self._gafaelfawr.create(namespace, objects.ingress, replace=True)
        await self._service.create(namespace, objects.service, replace=True)
        await self._job.create(namespace, objects.job, replace=True)

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
        TimeoutError
            Raised if the deletion of any individual object took longer than
            the Kubernetes delete timeout.
        """
        await self._gafaelfawr.delete(name, namespace, wait=True)
        await self._ingress.wait_for_deletion(name, namespace)
        await self._service.delete(name, namespace, wait=True)
        await self._job.delete(name, namespace, wait=True)

    async def namespace_exists(self, name: str) -> bool:
        """Check whether a namespace is present.

        Parameters
        ----------
        name
            Name of the namespace.

        Returns
        -------
        bool
            `True` if the namespace is present, `False` otherwise.
        """
        return await self._namespace.read(name) is not None

    async def read_fileserver_state(
        self, namespace: str
    ) -> dict[str, FileserverStateObjects]:
        """Read Kubernetes objects for all running fileservers.

        Assumes that all objects have the same name as the ``Job``.

        Parameters
        ----------
        namespace
            Namespace in which to look for running fileservers.

        Returns
        -------
        dict of FileserverStateObjects
            Dictionary mapping usernames to the state of their running
            fileservers.
        """
        selector = "nublado.lsst.io/category=fileserver"
        jobs = await self._job.list(namespace, label_selector=selector)

        # For each job, figure out the corresponding username from labels and
        # retrieve the additional objects we care about.
        state: dict[str, FileserverStateObjects] = {}
        for job in jobs:
            username = job.metadata.labels.get("nublado.lsst.io/user")
            if not username:
                continue

            # Check if we already saw a Job for this user, and if so, complain
            # and ignore the second one.
            if username in state:
                other = state[username].job
                msg = (
                    f"Duplicate jobs for user ({job.metadata.name} and"
                    f" {other.metadata.name}), ignoring the first"
                )
                self._logger.warning(msg, user=username, namespace=namespace)
                continue

            # Retrieve the Pod if it exists, complaining and ignoring if we
            # saw duplicate Pods for the same Job.
            pod = None
            try:
                pod = await self._get_pod_for_job(job.metadata.name, namespace)
            except MissingObjectError:
                pass
            except DuplicateObjectError as e:
                msg = f"{e!s}, ignoring them all"
                self._logger.warning(msg, user=username, namespace=namespace)

            # Retrieve the Ingress if it exists, and then put the objects into
            # the state map.
            ingress = await self._ingress.read(job.metadata.name, namespace)
            objects = FileserverStateObjects(job=job, pod=pod, ingress=ingress)
            state[username] = objects

        # Return the state map of everything we found.
        return state

    async def watch_pods(self, namespace: str) -> AsyncIterator[PodChange]:
        """Watches the file server namespace for pod phase changes.

        Technically, this iterator detects any change to a pod and returns its
        current phase. The change may not be a phase change. That's good
        enough for our purposes.

        It will continue forever until cancelled. It is meant to be run from a
        background task handling file server pod phase changes.

        Parameters
        ----------
        namespace
            Namespace to watch for changes.

        Yields
        ------
        PodChange
            Phase change of a pod in this namespace.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        async for change in self._pod.watch_pod_changes(namespace):
            yield change

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
