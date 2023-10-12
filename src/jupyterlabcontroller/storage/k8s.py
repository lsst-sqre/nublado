"""Kubernetes storage layer for the Nublado lab controller."""

from __future__ import annotations

from datetime import timedelta

from kubernetes_asyncio.client import ApiClient, V1Pod
from structlog.stdlib import BoundLogger

from ..exceptions import DuplicateObjectError, MissingObjectError
from .kubernetes.deleter import JobStorage
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
        self._logger = logger
        self._ingress = IngressStorage(kubernetes_client, logger)
        self._job = JobStorage(kubernetes_client, logger)
        self._namespace = NamespaceStorage(kubernetes_client, logger)
        self._pod = PodStorage(kubernetes_client, logger)

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
