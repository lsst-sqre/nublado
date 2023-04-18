"""Service to manage user fileservers."""


from __future__ import annotations

import asyncio
from typing import Any, Optional, Set
from urllib.parse import urlparse

from kubernetes_asyncio.client import (
    V1Container,
    V1ContainerPort,
    V1EnvVar,
    V1HostPathVolumeSource,
    V1Job,
    V1JobSpec,
    V1NFSVolumeSource,
    V1ObjectMeta,
    V1PodSecurityContext,
    V1PodSpec,
    V1PodTemplateSpec,
    V1ResourceRequirements,
    V1SecurityContext,
    V1Service,
    V1ServicePort,
    V1ServiceSpec,
    V1Volume,
    V1VolumeMount,
)
from safir.slack.webhook import SlackWebhookClient
from structlog.stdlib import BoundLogger

from ..config import Config, FileMode
from ..constants import FILESERVER_RECONCILIATION_INTERVAL
from ..exceptions import KubernetesError
from ..models.domain.fileserver import FileserverUserMap
from ..models.domain.lab import LabVolumeContainer as VolumeContainer
from ..models.v1.lab import UserInfo
from ..storage.k8s import K8sStorageClient


class FileserverReconciler:
    def __init__(
        self,
        *,
        config: Config,
        user_map: FileserverUserMap,
        logger: BoundLogger,
        k8s_client: K8sStorageClient,
    ) -> None:
        self.fs_namespace = config.fileserver.namespace
        self.user_map = user_map
        self.k8s_client = k8s_client
        self._logger = logger
        self._tasks: Set[asyncio.Task] = set()
        self._started = False

    async def start(self) -> None:
        if not await self.k8s_client.check_namespace(self.fs_namespace):
            self._logger.warning(
                "No namespace '{self.fs_namespace}'; cannot start"
            )
            return
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
        while self._started:
            await self.reconcile_user_map()
            await asyncio.sleep(
                FILESERVER_RECONCILIATION_INTERVAL.total_seconds()
            )

    async def stop(self) -> None:
        if not self._started:
            msg = "Fileserver reconciliation already stopped"
            self._logger.warning(msg)
            return
        self._started = False
        for tsk in self._tasks:
            tsk.cancel()

    async def reconcile_user_map(self) -> None:
        self._logger.debug("Reconciling fileserver user map")
        namespace = self.fs_namespace
        if not await self.k8s_client.check_namespace(namespace):
            self._logger.warning(
                f"No fileserver namespace '{namespace}'; no fileserver users"
            )
            return
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
            rmuser_task = asyncio.create_task(
                self.k8s_client.remove_fileserver(user, namespace)
            )
            self._tasks.add(rmuser_task)
            rmuser_task.add_done_callback(self._tasks.discard)
        # No need to create anything else for new ones--we know they're
        # running.
        await self.user_map.bulk_update(observed_map)
        self._logger.debug("Filserver user map reconciliation complete")
        self._logger.debug(f"Users with fileservers: {observed_users}")


class FileserverManager:
    def __init__(
        self,
        *,
        user_map: FileserverUserMap,
        logger: BoundLogger,
        config: Config,
        k8s_client: K8sStorageClient,
        slack_client: Optional[SlackWebhookClient] = None,
    ) -> None:
        self.fs_namespace = config.fileserver.namespace
        self.user_map = user_map
        self._logger = logger
        self.config = config
        self.k8s_client = k8s_client
        self._tasks: Set[asyncio.Task] = set()

    async def create_fileserver_if_needed(self, user: UserInfo) -> bool:
        """If the user doesn't have a fileserver, create it.  If the user
        already has a fileserver, just return.

        This gets called by the handler when a user comes in through the
        /file ingress.
        """
        username = user.username
        self._logger.info(f"Fileserver requested for {username}")
        if not (
            await self.user_map.get(username)
            and await self.k8s_client.check_fileserver_present(
                username, self.fs_namespace
            )
        ):
            try:
                if not await self._create_fileserver(user):
                    return False
            except KubernetesError:
                self._logger.error(
                    f"Fileserver creation for {username} failed: deleting "
                    + "fileserver objects."
                )
                await self.delete_fileserver(username)
                raise
            await self.user_map.set(username)
        return True

    async def _create_fileserver(self, user: UserInfo) -> bool:
        """Create a fileserver for the given user.  Wait for it to be
        operational.  If we can't build it, return False.
        """
        username = user.username
        self._logger.info(f"Creating new fileserver for {username}")
        namespace = self.fs_namespace
        if not await self.k8s_client.check_namespace(namespace):
            self._logger.warning("No fileserver namespace '{namespace}'")
            return False
        job = self._build_fileserver_job(user)
        gf_ingress = self._build_fileserver_ingress(user.username)
        service = self._build_fileserver_service(user.username)
        # We put this all in k8s_client so it can manage its own lock
        return await self.k8s_client.create_fileserver(
            username=username,
            namespace=namespace,
            job=job,
            service=service,
            gf_ingress=gf_ingress,
        )

    def _build_fileserver_metadata(self, username: str) -> V1ObjectMeta:
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
        obj_name = f"{username}-fs"
        return V1ObjectMeta(
            name=obj_name,
            namespace=self.fs_namespace,
            labels={
                "argocd.argoproj.io/instance": "fileservers",
                "lsst.io/category": "fileserver",
                "lsst.io/user": username,
            },
            annotations={
                "argocd.argoproj.io/compare-options": "IgnoreExtraneous",
                "argocd.argoproj.io/sync-options": "Prune=false",
            },
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
                spec=pod_spec,
                metadata=self._build_fileserver_metadata(username),
            ),
        )
        job = V1Job(
            metadata=self._build_fileserver_metadata(username),
            spec=job_spec,
        )
        return job

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
        volume_data = self._build_volumes()
        volumes = [v.volume for v in volume_data]
        mounts = [v.volume_mount for v in volume_data]

        username = user.username
        # Additional environment variables to set.
        env = [
            V1EnvVar(name="WORBLEHAT_BASE_HREF", value=f"/files/{username}"),
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
            # This is a guess.  Large file transfer is quite slow at
            # these settings, but we really don't intend to allow the RSP
            # to be used as a bulk download service.  Sensibly-sized things
            # such as notebooks (without enormous rendered output, anyway)
            # are actually pretty snappy.
            resources=V1ResourceRequirements(
                limits={
                    "cpu": "100m",
                    "memory": "128M",
                }
            ),
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
        #
        podspec = V1PodSpec(
            containers=[container],
            restart_policy="Never",
            security_context=V1PodSecurityContext(
                run_as_user=user.uid,
                run_as_group=user.gid,
                run_as_non_root=True,
                fs_group=user.gid,
                supplemental_groups=[x.id for x in user.groups],
            ),
            volumes=volumes,
        )
        return podspec

    def _build_volumes(self) -> list[VolumeContainer]:
        vconfig = self.config.lab.volumes
        vols = []
        for storage in vconfig:
            ro = False
            if storage.mode == FileMode.RO:
                ro = True
            vname = storage.container_path.replace("/", "_")[1:]
            if not storage.server:
                vol = V1Volume(
                    host_path=V1HostPathVolumeSource(path=storage.server_path),
                    name=vname,
                )
            else:
                vol = V1Volume(
                    nfs=V1NFSVolumeSource(
                        path=storage.server_path,
                        read_only=ro,
                        server=storage.server,
                    ),
                    name=vname,
                )
            vm = V1VolumeMount(
                mount_path="/mnt" + storage.container_path,
                read_only=ro,
                name=vname,
            )
            vols.append(VolumeContainer(volume=vol, volume_mount=vm))
        return vols

    def _build_custom_object_metadata(self, username: str) -> dict[str, Any]:
        obj_name = f"{username}-fs"
        apj = "argocd.argoproj.io"
        md_obj = {
            "name": obj_name,
            "namespace": self.fs_namespace,
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

    def build_fileserver_ingress_spec(self, username: str) -> dict[str, Any]:
        # The Gafaelfawr Ingress is a CRD, so creating it is a bit different.
        namespace = self.fs_namespace
        base_url = self.config.base_url
        host = urlparse(base_url).hostname
        obj_name = f"{username}-fs"
        # I feel like I should apologize for this object I'm returning.
        return {
            "apiVersion": "gafaelfawr.lsst.io/v1alpha1",
            "kind": "GafaelfawrIngress",
            "metadata": {
                "name": obj_name,
                "namespace": namespace,
                "labels": {"app": obj_name},
            },
            "metadata": self._build_custom_object_metadata(username),
            "template": {
                "metadata": self._build_custom_object_metadata(username),
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
            metadata=self._build_fileserver_metadata(username),
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
        if not await self.k8s_client.check_namespace(self.fs_namespace):
            return
        await self.user_map.remove(username)
        await self.k8s_client.remove_fileserver(username, self.fs_namespace)
