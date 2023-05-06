"""Service to manage user fileservers."""


from __future__ import annotations

import asyncio
from typing import Any, Optional, Set
from urllib.parse import urlparse

from kubernetes_asyncio.client import (
    V1Container,
    V1ContainerPort,
    V1EnvVar,
    V1Job,
    V1JobSpec,
    V1ObjectMeta,
    V1PodSecurityContext,
    V1PodSpec,
    V1PodTemplateSpec,
    V1ResourceRequirements,
    V1SecurityContext,
    V1Service,
    V1ServicePort,
    V1ServiceSpec,
)
from safir.slack.webhook import SlackWebhookClient
from structlog.stdlib import BoundLogger

from ..config import Config
from ..constants import FILESERVER_RECONCILIATION_INTERVAL
from ..models.domain.fileserver import FileserverUserMap
from ..models.v1.lab import UserInfo
from ..storage.k8s import K8sStorageClient
from ..util import metadata_to_dict
from .builder import LabBuilder

"""Neither the FileserverReconciler nor the FileserverManager should be
addressed directly.  All requests to them should go through the
FileserverStateManager that created them.
"""


class FileserverManager:
    def __init__(
        self,
        *,
        user_map: FileserverUserMap,
        logger: BoundLogger,
        config: Config,
        k8s_client: K8sStorageClient,
        lock: dict[str, asyncio.Lock],
        slack_client: Optional[SlackWebhookClient] = None,
    ) -> None:
        self.config = config
        self.namespace = config.fileserver.namespace
        self.user_map = user_map
        self._lock = lock
        self._logger = logger
        self.k8s_client = k8s_client
        self._tasks: Set[asyncio.Task] = set()
        self._builder: LabBuilder = LabBuilder(config=config.lab)

    async def create_fileserver_if_needed(self, user: UserInfo) -> None:
        """If the user doesn't have a fileserver, create it.  If the user
        already has a fileserver, just return.

        This gets called by the handler when a user comes in through the
        /files ingress.
        """
        username = user.username
        self._logger.info(f"Fileserver requested for {username}")
        if not (
            await self.user_map.get(username)
            and await self.k8s_client.check_fileserver_present(
                username, self.namespace
            )
        ):
            try:
                await self._create_fileserver(user)
            except Exception as exc:
                self._logger.error(
                    f"Fileserver creation for {username} failed with {exc}"
                    + ": deleting fileserver objects."
                )
                await self.delete_fileserver(username)
                raise
        return

    async def _create_fileserver(self, user: UserInfo) -> None:
        """Create a fileserver for the given user.  Wait for it to be
        operational.  If we can't build it, raise an error.
        """
        username = user.username
        async with self._lock[username]:
            self._logger.info(f"Creating new fileserver for {username}")
            namespace = self.namespace
            gf_ingress = self._build_fileserver_ingress(user.username)
            service = self._build_fileserver_service(user.username)
            job = self._build_fileserver_job(user)
            self._logger.debug(
                "...creating new gafawelfawrfingress for " + username
            )
            await self.k8s_client.create_fileserver_gafaelfawringress(
                username, namespace, spec=gf_ingress
            )
            self._logger.debug(f"...creating new job for {username}")
            await self.k8s_client.create_fileserver_job(
                username, namespace, job
            )
            self._logger.debug(f"...creating new service for {username}")
            await self.k8s_client.create_fileserver_service(
                username, namespace, spec=service
            )
            await self._wait_for_fileserver(username, namespace)
            await self.user_map.set(username)

    async def _wait_for_fileserver(
        self, username: str, namespace: str
    ) -> None:
        # FIXME watch for events, don't poll.
        timeout = 60.0
        interval = 3.9
        async with asyncio.timeout(timeout):
            # FIXME use an event watch, not a poll?
            while True:
                good = await self.k8s_client.check_fileserver_present(
                    username, namespace
                )
                if good:
                    self._logger.info(f"Fileserver created for {username}")
                    return
                await asyncio.sleep(interval)

    def _build_metadata(self, username: str) -> V1ObjectMeta:
        """Construct metadata for the user's fileserver objects.

        Parameters
        ----------
        username
            User name

        Returns
        -------
        V1ObjectMeta
            Kubernetes metadata specification for that user's fileserver
            objects.
        """
        return self.k8s_client.standard_metadata(
            name=f"{username}-fs",
            namespace=self.namespace,
            category="fileserver",
            username=username,
        )

    def _build_fileserver_job(self, user: UserInfo) -> V1Job:
        """Construct the job specification for the user's fileserver
        environment.

        Parameters
        ----------
        user
            User identity information.

        Returns
        -------
        V1Job
            Kubernetes job object for that user's fileserver environment.
        """
        username = user.username
        pod_spec = self._build_fileserver_pod_spec(user)
        job_spec = V1JobSpec(
            template=V1PodTemplateSpec(
                spec=pod_spec, metadata=self._build_metadata(username)
            ),
        )
        job = V1Job(
            metadata=self._build_metadata(username),
            spec=job_spec,
        )
        return job

    def _build_fileserver_resources(self) -> V1ResourceRequirements | None:
        #
        # In practice, limits of 100m CPU and 128M of memory seem fine.
        #
        # This assert will always succeed, because we cannot instantiate
        # the class without a fileserver config.  Mypy is dumb sometimes.
        assert self.config.fileserver is not None
        resources = self.config.fileserver.resources
        # Handle the degenerate cases first.
        if resources is None:
            return None
        if (
            not resources.limits.cpu
            and not resources.limits.memory
            and not resources.requests.cpu
            and not resources.requests.memory
        ):
            return None
        lim_dict = {}
        req_dict = {}
        if resources.limits.cpu:
            lim_dict["cpu"] = str(resources.limits.cpu)
        if resources.limits.memory:
            lim_dict["memory"] = str(resources.limits.memory)
        if not resources.requests.cpu:
            if resources.limits.cpu:
                # Our 25% heuristic seems to work fine
                cpu = resources.limits.cpu / 4.0
                if cpu < 0.001:
                    cpu = 0.001  # K8s granularity limitation.
                req_dict["cpu"] = str(cpu)
        if not resources.requests.memory:
            if resources.limits.memory:
                mem = int(resources.limits.memory / 4)
                # Sane-architecture granularity limitation.
                #
                # I mean, I'm being defensive here, but let's hope that no one
                # ever asks for a CPU limit of less than four millicores, or
                # specifies a number of bytes that's not divisible by four
                # for a memory limit.
                #
                req_dict["memory"] = str(mem)
        else:
            if resources.requests.cpu:
                req_dict["cpu"] = str(resources.requests.cpu)
            if resources.requests.memory:
                req_dict["memory"] = str(resources.requests.memory)
        return V1ResourceRequirements(limits=lim_dict, requests=req_dict)

    def _build_fileserver_pod_spec(self, user: UserInfo) -> V1PodSpec:
        """Construct the pod specification for the user's fileserver pod.

        Parameters
        ----------
        user
            User identity information.

        Returns
        -------
        V1PodSpec
            Kubernetes pod specification for that user's fileserver pod.
        """
        # This assert will always succeed, because we cannot instantiate
        # the class without a fileserver config.  Mypy is dumb sometimes.
        assert self.config.fileserver is not None

        volume_data = self._builder.build_lab_config_volumes(prefix="/mnt")
        volumes = [v.volume for v in volume_data]
        mounts = [v.volume_mount for v in volume_data]
        resource_data = self._build_fileserver_resources()
        username = user.username
        # Additional environment variables to set.
        env = [
            V1EnvVar(
                name="WORBLEHAT_BASE_HREF",
                value=(
                    self.config.fileserver.path_prefix + f"/files/{username}"
                ),
            ),
            V1EnvVar(
                name="WORBLEHAT_TIMEOUT",
                value=str(self.config.fileserver.timeout),
            ),
            V1EnvVar(name="WORBLEHAT_DIR", value="/mnt"),
        ]
        image = self.config.fileserver.image + ":" + self.config.fileserver.tag
        # Specification for the user's container.
        container = V1Container(
            name="fileserver",
            env=env,
            image=image,
            image_pull_policy=self.config.fileserver.pull_policy.value,
            ports=[V1ContainerPort(container_port=8000, name="http")],
            resources=resource_data,
            security_context=V1SecurityContext(
                run_as_non_root=True,
                run_as_user=user.uid,
                run_as_group=user.gid,
                allow_privilege_escalation=False,
                read_only_root_filesystem=True,
            ),
            volume_mounts=mounts,
        )

        # _Build the pod specification itself.
        # FIXME work out tolerations
        podspec = V1PodSpec(
            containers=[container],
            restart_policy="Never",
            security_context=V1PodSecurityContext(
                run_as_user=user.uid,
                run_as_group=user.gid,
                run_as_non_root=True,
                supplemental_groups=[x.id for x in user.groups],
            ),
            volumes=volumes,
        )
        return podspec

    def _build_custom_object_metadata(self, username: str) -> dict[str, Any]:
        obj_name = f"{username}-fs"
        apj = "argocd.argoproj.io"
        md_obj = {
            "name": obj_name,
            "namespace": self.namespace,
            "labels": {
                f"{apj}/instance": "fileservers",
                "lsst.io/category": "fileserver",
                "lsst.io/user": username,
            },
            "annotations": {
                f"{apj}/compare-options": "IgnoreExtraneous",
                f"{apj}/sync-options": "Prune=false",
            },
        }
        return md_obj

    def _build_fileserver_ingress(self, username: str) -> dict[str, Any]:
        # The Gafaelfawr Ingress is a CRD, so creating it is a bit different.
        base_url = self.config.base_url
        host = urlparse(base_url).hostname
        # I feel like I should apologize for this object I'm returning.
        # Note: camelCase, not snake_case
        return {
            "apiVersion": "gafaelfawr.lsst.io/v1alpha1",
            "kind": "GafaelfawrIngress",
            "metadata": metadata_to_dict(self._build_metadata(username)),
            "config": {
                "baseUrl": base_url,
                "scopes": {"all": ["exec:notebook"]},
                "loginRedirect": False,
                "authType": "basic",
            },
            "template": {
                "metadata": metadata_to_dict(self._build_metadata(username)),
                "spec": {
                    "rules": [
                        {
                            "host": host,
                            "http": {
                                "paths": [
                                    {
                                        "path": f"/files/{username}",
                                        "pathType": "Prefix",
                                        "backend": {
                                            "service": {
                                                "name": f"{username}-fs",
                                                "port": {"number": 8000},
                                            }
                                        },
                                    }
                                ]
                            },
                        }
                    ]
                },
            },
        }

    def _build_fileserver_service(self, username: str) -> V1Service:
        service = V1Service(
            metadata=self._build_metadata(username),
            spec=V1ServiceSpec(
                ports=[V1ServicePort(port=8000, target_port=8000)],
                selector={
                    "lsst.io/category": "fileserver",
                    "lsst.io/user": username,
                },
            ),
        )
        return service

    async def delete_fileserver(self, username: str) -> None:
        namespace = self.namespace
        async with self._lock[username]:
            await self.user_map.remove(username)
            await self.k8s_client.delete_fileserver_gafaelfawringress(
                username, namespace
            )
            await self.k8s_client.delete_fileserver_service(
                username, namespace
            )
            await self.k8s_client.delete_fileserver_job(username, namespace)
            # This next bit is what takes the time--the method does not
            # return until the fileserver objects are gone.
            await self.k8s_client.wait_for_fileserver_object_deletion(
                username, namespace
            )
        del self._lock[username]


class FileserverReconciler:
    def __init__(
        self,
        *,
        config: Config,
        user_map: FileserverUserMap,
        logger: BoundLogger,
        k8s_client: K8sStorageClient,
        lock: dict[str, asyncio.Lock],
        manager: FileserverManager,
    ) -> None:
        self.fs_namespace = config.fileserver.namespace
        self.user_map = user_map
        self.k8s_client = k8s_client
        self._lock = lock
        self._logger = logger
        self._manager = manager
        self._tasks: Set[asyncio.Task] = set()
        self._started = False
        self._builder = LabBuilder(config=config.lab)

    async def start(self) -> None:
        if self._started:
            msg = "Fileserver reconciliation already running; cannot start"
            self._logger.warning(msg)
            return
        self._started = True
        self._logger.info("Starting fileserver reconciliation")
        reconciliation_task = asyncio.create_task(self._reconciliation_loop())
        self._tasks.add(reconciliation_task)
        reconciliation_task.add_done_callback(self._tasks.discard)

    async def _reconciliation_loop(self) -> None:
        # FIXME this should be event/watch based, rather than polling.
        while self._started:
            await self.reconcile_user_map()
            await asyncio.sleep(
                FILESERVER_RECONCILIATION_INTERVAL.total_seconds()
            )

    async def stop(self) -> None:
        # If you call this when it's already stopped or stopping it doesn't
        # care.
        self._started = False
        for tsk in self._tasks:
            tsk.cancel()

    async def reconcile_user_map(self) -> None:
        self._logger.debug("Reconciling fileserver user map")
        namespace = self.fs_namespace
        mapped_users = set(await self.user_map.list_users())
        observed_map = await self.k8s_client.get_observed_fileserver_state(
            namespace
        )
        # Tidy up any no-longer-running users.  They aren't running, but they
        # might have some objects remaining.
        observed_users = set(observed_map.keys())
        missing_users = mapped_users - observed_users
        if missing_users:
            self._logger.info(
                f"Users {missing_users} have broken fileservers; removing."
            )
        for user in missing_users:
            await self._manager.delete_fileserver(user)
        # No need to create anything else for new ones--we know they're
        # running.
        for user in observed_users:
            async with self._lock[user]:
                await self.user_map.set(user)
        self._logger.debug("Filserver user map reconciliation complete")
        self._logger.debug(f"Users with fileservers: {observed_users}")
