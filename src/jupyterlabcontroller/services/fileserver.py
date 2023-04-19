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
from ..models.domain.fileserver import FileserverUserMap
from ..models.domain.lab import LabVolumeContainer as VolumeContainer
from ..models.v1.lab import UserInfo
from ..storage.k8s import K8sStorageClient


class FileserverManager:
    def __init__(
        self,
        *,
        fs_namespace: str,
        user_map: FileserverUserMap,
        logger: BoundLogger,
        config: Config,
        k8s_client: K8sStorageClient,
        slack_client: Optional[SlackWebhookClient] = None,
    ) -> None:
        self.fs_namespace = fs_namespace
        self.user_map = user_map
        self._logger = logger
        self.config = config
        self.k8s_client = k8s_client
        self._slack_client = slack_client
        self._tasks: Set[asyncio.Task] = set()

    async def reconcile_user_map(self) -> None:
        namespace = self.fs_namespace
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

    async def create_fileserver(self, user: UserInfo) -> None:
        """Create a fileserver for the given user.  Wait for it to be
        operational.

        This is the thing that gets called by the handler when a user comes in
        through this service's ingress and the user does not already have a
        running fileserver.
        """
        username = user.username
        namespace = self.fs_namespace
        timeout = 60.0
        interval = 4.0

        pod_spec = self.build_fileserver_pod_spec(user)
        galing_spec = self.build_fileserver_ingress_spec(user.username)
        await self.k8s_client.create_fileserver_deployment(
            username, namespace, pod_spec
        )
        await self.k8s_client.create_fileserver_service(username, namespace)
        await self.k8s_client.create_fileserver_gafaelfawringress(
            username, namespace, spec=galing_spec
        )

        async with asyncio.timeout(timeout):
            while True:
                good = await self.k8s_client.check_fileserver_present(
                    username, namespace
                )
                if good:
                    return
                await asyncio.sleep(interval)

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
        # Additional environment variables to set, apart from the ConfigMap.
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
            "apiVersion": "gafaelfawr.lsst.io/v1alpha1",
            "kind": "GafaelfawrIngress",
            "metadata": {
                "name": obj_name,
                "namespace": namespace,
                "labels": {"app": obj_name},
            },
            "config": {
                "baseUrl": base_url,
                "scopes": {"all": ["exec:notebook"]},
                "loginRedirect": False,
                "authType": "basic",
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
                                        "pathType": "Prefix",
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
