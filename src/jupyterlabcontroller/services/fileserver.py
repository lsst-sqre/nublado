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
    V1NFSVolumeSource,
    V1PodSecurityContext,
    V1PodSpec,
    V1ResourceRequirements,
    V1SecurityContext,
    V1Volume,
    V1VolumeMount,
)
from safir.slack.webhook import SlackWebhookClient
from structlog.stdlib import BoundLogger

from ..config import Config, FileMode
from ..constants import FILESERVER_RECONCILIATION_INTERVAL
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
            msg = "Fileserver reconciliation already running; cannot restart"
            self._logger.warning(msg)
            return
        self._started = True
        self._logger.info("Starting fileserver reconciliation")
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
        mapped_users = set(self.user_map.list_users())
        observed_map = await self.k8s_client.get_observed_fileserver_state(
            namespace
        )
        # Tidy up any no-longer-running users.  They aren't running, but they
        # might have some objects remaining.
        observed_users = set(observed_map.keys())
        missing_users = mapped_users - observed_users
        for user in missing_users:
            rmuser_task = asyncio.create_task(
                self.k8s_client.remove_fileserver(user, namespace)
            )
            self._tasks.add(rmuser_task)
            rmuser_task.add_done_callback(self._tasks.discard)
        # No need to create anything else for new ones--we know they're
        # running.
        self.user_map.bulk_update(observed_map)


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

    def list_users(self) -> list[str]:
        return self.user_map.list_users()

    async def create_fileserver_if_needed(self, user: UserInfo) -> bool:
        """If the user doesn't have a fileserver, create it.  If the user
        already has a fileserver, just return.

        This gets called by the handler when a user comes in through the
        /file ingress.
        """
        username = user.username
        if username not in self.list_users():
            if not await self.create_fileserver(user):
                return False
            self.user_map.set(username)
        return True

    async def create_fileserver(self, user: UserInfo) -> bool:
        """Create a fileserver for the given user.  Wait for it to be
        operational.  If we can't build it, return False.
        """
        username = user.username
        self._logger.debug(f"Creating new fileserver for {username}")
        namespace = self.fs_namespace
        if not await self.k8s_client.check_namespace(namespace):
            self._logger.warning("No fileserver namespace '{namespace}'")
            return False
        timeout = 60.0
        interval = 4.0

        pod_spec = self.build_fileserver_pod_spec(user)
        galing_spec = self.build_fileserver_ingress_spec(user.username)
        self._logger.debug(f"...creating new deployment for {username}")
        await self.k8s_client.create_fileserver_deployment(
            username, namespace, pod_spec
        )
        self._logger.debug(f"...creating new service for {username}")
        await self.k8s_client.create_fileserver_service(username, namespace)
        self._logger.debug(f"...creating new gfingress for {username}")
        await self.k8s_client.create_fileserver_gafaelfawringress(
            username, namespace, spec=galing_spec
        )
        self._logger.debug(f"...polling until objects appear for {username}")
        try:
            async with asyncio.timeout(timeout):
                while True:
                    good = await self.k8s_client.check_fileserver_present(
                        username, namespace
                    )
                    if good:
                        return True
                    await asyncio.sleep(interval)
        except asyncio.TimeoutError:
            self._logger.error(f"Fileserver for {username} did not appear.")
            return False

    def build_fileserver_pod_spec(self, user: UserInfo) -> V1PodSpec:
        """Construct the pod specification for the user's fileserver pod.

        Parameters
        ----------
        user
            User identity information.

        Returns
        -------
        V1PodSpec
            Kubernetes pod specification for that user's lab pod.
        """
        volume_data = self.build_volumes()
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
            image_pull_policy=self.config.fileserver.pull_policy,
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

        # Build the pod specification itself.
        # FIXME work out tolerations
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

    def build_volumes(self) -> list[VolumeContainer]:
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

    def build_fileserver_ingress_spec(self, username: str) -> dict[str, Any]:
        # The Gafaelfawr Ingress is a CRD, so creating it is a bit different.
        namespace = self.fs_namespace
        base_url = self.config.base_url
        host = urlparse(base_url).hostname
        obj_name = f"{username}-fs"
        # I feel like I should apologize for this object I'm returning.
        return {
            "api_version": "gafaelfawr.lsst.io/v1alpha1",
            "kind": "GafaelfawrIngress",
            "metadata": {
                "name": obj_name,
                "namespace": namespace,
                "labels": {"app": obj_name},
            },
            "config": {
                "base_url": base_url,
                "scopes": {"all": ["exec:notebook"]},
                "login_redirect": False,
                "auth_type": "basic",
            },
            "template": {
                "metadata": {"name": obj_name},
                "spec": {
                    "rules": [
                        {
                            "host": host,
                            "http": {
                                "paths": [
                                    {
                                        "path": f"/files/{username}",
                                        "path_type": "Prefix",
                                        "backend": {
                                            "service": {
                                                "name": obj_name,
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

    async def delete_fileserver(self, username: str) -> None:
        if not await self.k8s_client.check_namespace(self.fs_namespace):
            return
        await self.k8s_client.remove_fileserver(username, self.fs_namespace)
        self.user_map.remove(username)
