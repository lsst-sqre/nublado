"""Kubernetes storage layer for the Nublado lab controller."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

from kubernetes_asyncio import client
from kubernetes_asyncio.client import (
    ApiClient,
    V1ConfigMap,
    V1Job,
    V1ObjectMeta,
    V1Pod,
    V1ResourceQuota,
    V1Service,
)
from structlog.stdlib import BoundLogger

from ..constants import ARGO_CD_ANNOTATIONS
from ..exceptions import DuplicateObjectError, MissingObjectError
from ..models.domain.kubernetes import PodPhase, PropagationPolicy
from .kubernetes.creator import (
    ConfigMapStorage,
    PersistentVolumeClaimStorage,
    ResourceQuotaStorage,
)
from .kubernetes.custom import GafaelfawrIngressStorage
from .kubernetes.deleter import JobStorage, ServiceStorage
from .kubernetes.ingress import IngressStorage
from .kubernetes.namespace import NamespaceStorage
from .kubernetes.pod import PodStorage

__all__ = ["K8sStorageClient"]


class K8sStorageClient:
    def __init__(
        self,
        *,
        kubernetes_client: ApiClient,
        spawn_timeout: timedelta,
        logger: BoundLogger,
    ) -> None:
        self.k8s_api = kubernetes_client
        self.api = client.CoreV1Api(kubernetes_client)
        self._spawn_timeout = spawn_timeout
        self._logger = logger

        self._config_map = ConfigMapStorage(self.k8s_api, logger)
        self._gafaelfawr = GafaelfawrIngressStorage(self.k8s_api, logger)
        self._ingress = IngressStorage(self.k8s_api, logger)
        self._job = JobStorage(self.k8s_api, logger)
        self._namespace = NamespaceStorage(self.k8s_api, logger)
        self._pod = PodStorage(self.k8s_api, logger)
        self._pvc = PersistentVolumeClaimStorage(self.k8s_api, logger)
        self._quota = ResourceQuotaStorage(self.k8s_api, logger)
        self._service = ServiceStorage(self.k8s_api, logger)

    #
    # Exported methods useful for multiple services
    #

    async def get_pod(self, name: str, namespace: str) -> V1Pod | None:
        """Read a ``Pod`` object from Kubernetes.

        Parameters
        ----------
        name
            Name of the pod.
        namespace
            Namespace of the pod.

        Returns
        -------
        kubernetes_asyncio.client.V1Pod or None
            The ``Pod`` object, or `None` if it does not exist.

        Raises
        ------
        KubernetesError
            Raised if a Kubernetes API call fails.
        """
        return await self._pod.read(name, namespace)

    async def get_pod_phase(
        self, name: str, namespace: str
    ) -> PodPhase | None:
        """Get the phase of a currently running pod.

        Called whenever JupyterHub wants to check the status of running pods,
        so this will be called frequently and should be fairly quick.

        Parameters
        ----------
        name
            Name of the pod.
        namespace
            Namespace of the pod

        Returns
        -------
        PodPhase or None
            Phase of the pod or `None` if the pod does not exist.

        Raises
        ------
        KubernetesError
            Raised on failure to talk to Kubernetes.
        """
        pod = await self.get_pod(name, namespace)
        if pod is None:
            return None
        msg = f"Pod phase is {pod.status.phase}"
        self._logger.debug(msg, name=name, namespace=namespace)
        return pod.status.phase

    async def wait_for_pod_start(
        self, pod_name: str, namespace: str, timeout: timedelta | None = None
    ) -> PodPhase | None:
        """Waits for a pod to finish starting.

        Waits for the pod to reach a phase other than pending or unknown, and
        returns the new phase. We treat unknown like pending since we're
        running with a timeout anyway, and will eventually time out if we
        can't get back access to the node where the pod is running.

        Parameters
        ----------
        pod_name
            Name of the pod.
        namespace
            Namespace in which the pod is located.
        timeout
            Timeout to wait for the pod to start.

        Returns
        -------
        PodPhase
            New pod phase, or `None` if the pod has disappeared.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        return await self._pod.wait_for_phase(
            pod_name,
            namespace,
            until_not={PodPhase.UNKNOWN, PodPhase.PENDING},
            timeout=timeout or self._spawn_timeout,
        )

    async def wait_for_pod_stop(
        self, pod_name: str, namespace: str
    ) -> PodPhase | None:
        """Waits for a pod to terminate.

        Waits for the pod to reach a phase other than running or unknown, and
        returns the new phase. We treat unknown like running and assume
        eventually we will get back a real phase.

        Parameters
        ----------
        pod_name
            Name of the pod.
        namespace
            Namespace in which the pod is located.

        Returns
        -------
        PodPhase
            New pod phase, or `None` if the pod has disappeared.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        return await self._pod.wait_for_phase(
            pod_name,
            namespace,
            until_not={PodPhase.UNKNOWN, PodPhase.RUNNING},
            timeout=self._spawn_timeout,
        )

    async def watch_pod_events(
        self, pod_name: str, namespace: str
    ) -> AsyncIterator[str]:
        """Monitor the startup of a pod.

        Watches for events involving a pod, yielding them. Must be cancelled
        by the caller when the watch is no longer of interest.

        Parameters
        ----------
        pod_name
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
        async for message in self._pod.events_for_pod(pod_name, namespace):
            yield message

    def standard_metadata(
        self,
        name: str,
        namespace: str = "",
        category: str = "lab",
        username: str = "",
    ) -> V1ObjectMeta:
        """Create the standard metadata for an object.

        Parameters
        ----------
        name
            Name of the object.

        namespace
            Namespace of the object (optional, defaults to the empty string).

        category
            Category of the object (optional, defaults to ``lab``).

        username
            User for whom the object is created (optional, defaults to
            the empty string).

        Returns
        -------
        V1ObjectMeta
            Metadata for the object. For labs, this primarily adds Argo CD
            annotations to make user labs play somewhat nicely with Argo CD.
            For fileservers, this also adds labels we can use as selectors;
            this is necessary because all user fileservers run in a single
            namespace.
        """
        argo_app = "nublado-users"
        if category == "fileserver":
            argo_app = "fileservers"
        elif category == "prepuller":
            argo_app = ""
        labels = {
            "nublado.lsst.io/category": category,
        }
        if argo_app:
            labels["argocd.argoproj.io/instance"] = argo_app
        if username:
            labels["nublado.lsst.io/user"] = username
        annotations = ARGO_CD_ANNOTATIONS.copy()
        metadata = V1ObjectMeta(
            name=name,
            labels=labels,
            annotations=annotations,
        )
        if namespace:
            metadata.namespace = namespace
        return metadata

    async def delete_namespace(self, name: str, *, wait: bool = False) -> None:
        """Delete a Kubernetes namespace.

        If the namespace doesn't exist, the deletion is silently successful.

        Parameters
        ----------
        name
            Name of the namespace.
        wait
            Whether to wait for the namespace to be deleted.
        """
        await self._namespace.delete(name, wait=wait)

    async def get_config_map(
        self, name: str, namespace: str
    ) -> V1ConfigMap | None:
        """Read a ``ConfigMap`` object from Kubernetes.

        Parameters
        ----------
        name
            Name of the config map.
        namespace
            Namespace of the config map.

        Returns
        -------
        kubernetes_asyncio.client.V1ConfigMap or None
            ``ConfigMap`` object, or `None` if it does not exist.

        Raises
        ------
        KubernetesError
            Raised if a Kubernetes API call fails.
        """
        return await self._config_map.read(name, namespace)

    async def get_quota(
        self, name: str, namespace: str
    ) -> V1ResourceQuota | None:
        """Read a ``ResourceQuota`` object from Kubernetes.

        Parameters
        ----------
        name
            Name of the resource quota.
        namespace
            Namespace of the resource quota.

        Returns
        -------
        kubernetes_asyncio.client.V1ResourceQuota or None
            The ``ResourceQuota`` object, or `None` if it does not exist.

        Raises
        ------
        KubernetesError
            Raised if a Kubernetes API call fails.
        """
        return await self._quota.read(name, namespace)

    async def list_namespaces(self, prefix: str) -> list[str]:
        """List namespaces with the given prefix.

        Parameters
        ----------
        prefix
            Prefix of namespaces of interest. A dash (``-``) will be added.

        Returns
        -------
        list of str
            List of namespaces whose names start with that prefix.

        Raises
        ------
        KubernetesError
            Raised if a Kubernetes API call fails.
        """
        return [
            n.metadata.name
            for n in await self._namespace.list()
            if n.metadata.name.startswith(f"{prefix}-")
        ]

    #
    # Methods for user fileservers
    #

    async def check_namespace(self, name: str) -> bool:
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

    async def create_fileserver_job(self, namespace: str, job: V1Job) -> None:
        """Create a ``Job`` for a file server.

        For all of our fileserver objects, if we are being asked to create
        them, it means we thought, based on our user map that we did not have
        a working file server. Any objects we encounter are therefore left
        over from a non-functional file server that wasn't cleaned up
        properly. In that case, delete the old object and then create a new
        one.
        """
        await self._job.create(
            namespace,
            job,
            replace=True,
            propagation_policy=PropagationPolicy.FOREGROUND,
        )

    async def delete_fileserver_job(
        self, username: str, namespace: str
    ) -> None:
        await self._job.delete(
            f"{username}-fs",
            namespace,
            propagation_policy=PropagationPolicy.FOREGROUND,
        )

    async def create_fileserver_service(
        self, namespace: str, spec: V1Service
    ) -> None:
        """Create the ``Service`` for a file server.

        See `create_fileserver_job` for the rationale behind retrying a
        conflict on creation.
        """
        await self._service.create(namespace, spec, replace=True)

    async def delete_fileserver_service(
        self, username: str, namespace: str
    ) -> None:
        name = f"{username}-fs"
        await self._service.delete(name, namespace)

    async def create_fileserver_gafaelfawringress(
        self, namespace: str, spec: dict[str, Any]
    ) -> None:
        """Create the ``GafaelfawrIngress`` for a file server.

        See `create_fileserver_job` for the rationale behind retrying a
        conflict on creation.
        """
        await self._gafaelfawr.create(namespace, spec, replace=True)

    async def delete_fileserver_gafaelfawringress(
        self, username: str, namespace: str
    ) -> None:
        name = f"{username}-fs"
        await self._gafaelfawr.delete(name, namespace)

    async def get_observed_fileserver_state(
        self, namespace: str
    ) -> dict[str, bool]:
        """Get file server state from Kubernetes.

        Reconstruct the fileserver user map with what we can determine
        from the Kubernetes cluster.

        Objects with the name :samp:`{username}-fs` are presumed to be file
        server objects, where *username* can be assumed to be the name of the
        owning user.

        Returns
        -------
        dict of bool
            Users who currently have fileservers.
        """
        observed_state: dict[str, bool] = {}
        if not await self.check_namespace(namespace):
            raise MissingObjectError(
                f"Missing user fileservers namespace {namespace}",
                kind="Namespace",
                name=namespace,
            )

        # Get all jobs with the right labels and extract the users.
        selector = "nublado.lsst.io/category=fileserver"
        users = [
            j.metadata.labels.get("nublado.lsst.io/user")
            for j in await self._job.list(namespace, label_selector=selector)
        ]

        # For each of these, check whether the fileserver is present
        for user in users:
            self._logger.debug(f"Checking user {user}")
            good = await self.check_fileserver_present(user, namespace)
            self._logger.debug(f"{user} fileserver good?  {good}")
            if good:
                observed_state[user] = True
        return observed_state

    async def check_fileserver_present(
        self, username: str, namespace: str
    ) -> bool:
        """Check if a file server is present.

        Our determination of whether a user has a fileserver is this:

        We assume all fileserver objects are named <username>-fs, which we
        can do, since we created them and that's the convention we chose.

        A fileserver is working if:

        #. it has exactly one Pod in Running state due to a Job of the
           right name, and
        #. it has an Ingress, which has status.load_balancer.ingress, and
           that inner ingress has an attribute "ip" which is not the
           empty string.

        We do not check the GafaelfawrIngress, because the Custom API is
        clumsy, and the created Ingress is a requirement for whether the
        fileserver is running.  Although we create a Service, there's
        not much that can go wrong with it, so we opt to save the API
        call by assuming it's fine.
        """
        name = f"{username}-fs"
        self._logger.debug(f"Checking whether {username} has fileserver")
        self._logger.debug(f"...checking Job for {username}")
        job = await self._job.read(name, namespace)
        if job is None:
            self._logger.debug(f"...Job {name} for {username} not found.")
            return False
        # OK, we have a job.  Now let's see if the Pod from that job has
        # arrived...
        self._logger.debug(f"...checking Pod for {username}")
        pod = await self.get_fileserver_pod_for_user(username, namespace)
        if pod is None:
            self._logger.info(f"No Pod for {username}")
            return False
        if pod.status is None:
            self._logger.info(f"No Pod status for {pod.metadata.name}")
            return False
        if pod.status.phase != "Running":
            self._logger.info(
                f"Pod for {username} is in phase "
                f"'{pod.status.phase}', not 'Running'."
            )
            return False
        self._logger.debug(f"...checking Ingress for {username}")
        ingress = await self._ingress.read(name, namespace)
        if not ingress:
            self._logger.info(f"...Ingress {name} for {username} not found.")
            return False
        if not self._ingress.has_ip_address(ingress):
            self._logger.info(
                f"...Ingress {name} for {username} does not have address."
            )
            return False
        self._logger.debug(f"...fileserver for {username} is OK.")
        return True

    async def wait_for_fileserver_object_deletion(
        self, username: str, namespace: str
    ) -> None:
        """Wait for the key fileserver objects (Ingress and Job) to
        be deleted.  We will presume that the GafaelfawrIngress deletion
        happens basically immediately after its corresponding Ingress
        is deleted.
        """
        name = f"{username}-fs"
        self._logger.debug("Waiting for fileserver Ingress deletion")
        await self._ingress.wait_for_deletion(name, namespace)
        self._logger.debug("Waiting for fileserver Job deletion")
        await self._job.wait_for_deletion(name, namespace)

    async def get_fileserver_pod_for_user(
        self, username: str, namespace: str
    ) -> V1Pod | None:
        selector = f"job-name={username}-fs"
        pods = await self._pod.list(namespace, label_selector=selector)
        if not pods:
            return None
        if len(pods) > 1:
            msg = f"Multiple pods match job {username}-fs"
            raise DuplicateObjectError(msg, kind="Pod", namespace=namespace)
        return pods[0]

    async def wait_for_user_fileserver_ingress_ready(
        self, username: str, namespace: str, timeout: timedelta
    ) -> None:
        name = f"{username}-fs"
        await self._ingress.wait_for_ip_address(name, namespace, timeout)
