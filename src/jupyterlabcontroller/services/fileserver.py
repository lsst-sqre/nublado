"""Service to manage user fileservers."""


from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import timedelta
from typing import Any
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
from structlog.stdlib import BoundLogger

from ..config import Config
from ..constants import LIMIT_TO_REQUEST_RATIO
from ..exceptions import DisabledError, MissingObjectError
from ..models.domain.fileserver import FileserverUserMap
from ..models.v1.lab import UserInfo
from ..storage.k8s import K8sStorageClient
from ..util import metadata_to_dict
from .builder import LabBuilder


class FileserverStateManager:
    def __init__(
        self,
        *,
        logger: BoundLogger,
        config: Config,
        kubernetes: K8sStorageClient,
    ) -> None:
        """The FileserverStateManager is a process-wide singleton."""
        self._config = config
        self._namespace = config.fileserver.namespace
        self._user_map = FileserverUserMap()
        # This maps usernames to locks, so we have a lock per user, and
        # if there is no lock for that user, requesting one gets you a
        # new lock.
        self._lock: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._logger = logger
        self._k8s_client = kubernetes
        self._tasks: set[asyncio.Task] = set()
        self._builder: LabBuilder = LabBuilder(config=config.lab)
        self._started = False
        # Maps users to the tasks watching for their pods to exit
        self._watches: set[asyncio.Task] = set()

    async def create(self, user: UserInfo) -> None:
        """If the user doesn't have a fileserver, create it.  If the user
        already has a fileserver, just return.

        This gets called by the handler when a user comes in through the
        /files ingress.
        """
        username = user.username
        self._logger.info(f"Fileserver requested for {username}")
        if not (
            await self._user_map.get(username)
            and await self._k8s_client.check_fileserver_present(
                username, self._namespace
            )
        ):
            try:
                await self._create_fileserver(user)
            except Exception as exc:
                self._logger.error(
                    f"Fileserver creation for {username} failed with {exc}"
                    + ": deleting fileserver objects."
                )
                await self.delete(username)
                raise
        return

    async def _create_fileserver(self, user: UserInfo) -> None:
        """Create a fileserver for the given user.  Wait for it to be
        operational.  If we can't build it, raise an error.
        """
        username = user.username
        async with self._lock[username]:
            self._logger.info(f"Creating new fileserver for {username}")
            namespace = self._namespace
            gf_ingress = self._build_fileserver_ingress(user.username)
            service = self._build_fileserver_service(user.username)
            job = self._build_fileserver_job(user)
            self._logger.debug(
                "...creating new gafawelfawrfingress for " + username
            )
            await self._k8s_client.create_fileserver_gafaelfawringress(
                username, namespace, spec=gf_ingress
            )
            self._logger.debug(f"...creating new job for {username}")
            await self._k8s_client.create_fileserver_job(namespace, job)
            self._logger.debug(f"...creating new service for {username}")
            await self._k8s_client.create_fileserver_service(
                namespace, service
            )
            await self._wait_for_fileserver_start(username, namespace)
            task = asyncio.create_task(self._discard_when_done(username))
            self._watches.add(task)
            task.add_done_callback(self._watches.discard)
            await self._user_map.set(username)

    async def _wait_for_fileserver_start(
        self, username: str, namespace: str
    ) -> None:
        pod = await self._k8s_client.get_fileserver_pod_for_user(
            username, namespace
        )
        if pod is None:
            raise MissingObjectError(
                message=f"No pod for job fs-{username}",
                namespace=self._namespace,
                kind="Pod",
            )
        timeout = timedelta(seconds=self._config.fileserver.creation_timeout)
        await self._k8s_client.wait_for_pod_start(
            pod_name=pod.metadata.name,
            namespace=namespace,
            timeout=timeout,
        )
        # The ingress is the part that typically takes longest
        await self._k8s_client.wait_for_user_fileserver_ingress_ready(
            username,
            namespace,
            timeout=timedelta(
                seconds=self._config.fileserver.creation_timeout
            ),
        )

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
        return self._k8s_client.standard_metadata(
            name=f"{username}-fs",
            namespace=self._namespace,
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
        resources = self._config.fileserver.resources
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
                cpu = resources.limits.cpu / LIMIT_TO_REQUEST_RATIO
                if cpu < 0.001:
                    cpu = 0.001  # K8s granularity limitation.
                req_dict["cpu"] = str(cpu)
        if not resources.requests.memory:
            if resources.limits.memory:
                mem = int(resources.limits.memory / LIMIT_TO_REQUEST_RATIO)
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
        username = user.username
        volume_data = self._builder.build_lab_config_volumes(
            username, self._config.lab.volumes, prefix="/mnt"
        )
        volumes = [v.volume for v in volume_data]
        mounts = [v.volume_mount for v in volume_data]
        resource_data = self._build_fileserver_resources()
        # Additional environment variables to set.
        env = [
            V1EnvVar(
                name="WORBLEHAT_BASE_HREF",
                value=(
                    self._config.fileserver.path_prefix + f"/files/{username}"
                ),
            ),
            V1EnvVar(
                name="WORBLEHAT_TIMEOUT",
                value=str(self._config.fileserver.timeout),
            ),
            V1EnvVar(name="WORBLEHAT_DIR", value="/mnt"),
        ]
        image = (
            self._config.fileserver.image + ":" + self._config.fileserver.tag
        )
        # Specification for the user's container.
        container = V1Container(
            name="fileserver",
            env=env,
            image=image,
            image_pull_policy=self._config.fileserver.pull_policy.value,
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
            "namespace": self._namespace,
            "labels": {
                f"{apj}/instance": "fileservers",
                "nublado.lsst.io/category": "fileserver",
                "nublado.lsst.io/user": username,
            },
            "annotations": {
                f"{apj}/compare-options": "IgnoreExtraneous",
                f"{apj}/sync-options": "Prune=false",
            },
        }
        return md_obj

    def _build_fileserver_ingress(self, username: str) -> dict[str, Any]:
        # The Gafaelfawr Ingress is a CRD, so creating it is a bit different.
        base_url = self._config.base_url
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
                    "nublado.lsst.io/category": "fileserver",
                    "nublado.lsst.io/user": username,
                },
            ),
        )
        return service

    async def delete(self, username: str) -> None:
        if not self._started:
            raise DisabledError("Fileserver is not started.")
        namespace = self._namespace
        async with self._lock[username]:
            await self._user_map.remove(username)
            await self._k8s_client.delete_fileserver_gafaelfawringress(
                username, namespace
            )
            await self._k8s_client.delete_fileserver_service(
                username, namespace
            )
            await self._k8s_client.delete_fileserver_job(username, namespace)
            # This next bit is what takes the time--the method does not
            # return until the fileserver objects are gone.
            await self._k8s_client.wait_for_fileserver_object_deletion(
                username, namespace
            )

    async def list(self) -> list[str]:
        return await self._user_map.list()

    async def start(self) -> None:
        if not self._config.fileserver.enabled:
            raise DisabledError("Fileserver is disabled in configuration")
        if not await self._k8s_client.check_namespace(
            self._config.fileserver.namespace
        ):
            raise MissingObjectError(
                "File server namespace missing",
                kind="Namespace",
                name=self._config.fileserver.namespace,
            )
        await self._reconcile_user_map()
        self._started = True

    async def stop(self) -> None:
        # If you call this when it's already stopped or stopping it doesn't
        # care.
        #
        # We want to leave started fileservers running.  We will find them
        # again on our next restart, and user service will not be interrupted.
        #
        # No one can start a new server while self._started is False.
        self._started = False
        # Remove all pending fileserver watch tasks
        for task in self._watches:
            task.cancel()

    async def _discard_when_done(self, username: str) -> None:
        pod = await self._k8s_client.get_fileserver_pod_for_user(
            username, self._namespace
        )
        if pod is None:
            # This would be weird, since we just saw that the user
            # had a job with at least one active pod...
            raise MissingObjectError(
                message=f"No pod for job fs-{username}",
                namespace=self._namespace,
                kind="Pod",
            )
        podname = pod.metadata.name
        await self._k8s_client.wait_for_pod_stop(podname, self._namespace)
        await self.delete(username)

    async def _reconcile_user_map(self) -> None:
        """We need to run this on startup, to synchronize the
        user map resource with observed state."""
        self._logger.debug("Reconciling fileserver user map")
        mapped_users = set(await self.list())
        observed_map = await self._k8s_client.get_observed_fileserver_state(
            self._namespace
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
            await self.delete(user)
        # We know any observed users are running, so we need to create tasks
        # to clean them up when they exit, and then mark them as set in the
        # user map.
        for user in observed_users:
            async with self._lock[user]:
                task = asyncio.create_task(self._discard_when_done(user))
                self._watches.add(task)
                task.add_done_callback(self._watches.discard)
                await self._user_map.set(user)
        self._logger.debug("Filserver user map reconciliation complete")
        self._logger.debug(f"Users with fileservers: {observed_users}")
