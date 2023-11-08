"""Construction of Kubernetes objects for user fileservers."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from kubernetes_asyncio.client import (
    V1Container,
    V1ContainerPort,
    V1EnvVar,
    V1Job,
    V1JobSpec,
    V1ObjectMeta,
    V1Pod,
    V1PodSecurityContext,
    V1PodSpec,
    V1PodTemplateSpec,
    V1SecurityContext,
    V1Service,
    V1ServicePort,
    V1ServiceSpec,
)
from structlog.stdlib import BoundLogger

from ...config import EnabledFileserverConfig, LabVolume
from ...constants import ARGO_CD_ANNOTATIONS
from ...models.domain.fileserver import (
    FileserverObjects,
    FileserverStateObjects,
)
from ...models.v1.lab import UserInfo
from ...storage.kubernetes.ingress import ingress_has_ip_address
from .volumes import VolumeBuilder

__all__ = ["FileserverBuilder"]


class FileserverBuilder:
    """Construct Kubernetes objects for user fileservers.

    Parameters
    ----------
    config
        Fileserver configuration.
    base_url
        Base URL for this Notebook Aspect instance.
    volumes
        Volumes to mount in the user's fileserver.
    """

    def __init__(
        self,
        *,
        config: EnabledFileserverConfig,
        base_url: str,
        volumes: list[LabVolume],
        logger: BoundLogger,
    ) -> None:
        self._config = config
        self._base_url = base_url
        self._volumes = volumes
        self._logger = logger
        self._volume_builder = VolumeBuilder()

    def build(self, user: UserInfo) -> FileserverObjects:
        """Construct the objects that make up a user's fileserver.

        Parameters
        ----------
        user
            User for whom to create a fileserver.

        Returns
        -------
        FileserverObjects
            Kubernetes objects for the fileserver.
        """
        return FileserverObjects(
            ingress=self._build_ingress(user.username),
            service=self._build_service(user.username),
            job=self._build_job(user),
        )

    def build_name(self, username: str) -> str:
        """Construct the name of fileserver objects.

        Parameters
        ----------
        username
            Username the fileserver is for.

        Returns
        -------
        str
            Name of all Kubernetes objects for that fileserver.
        """
        return f"{username}-fs"

    def get_username_for_pod(self, pod: V1Pod) -> str | None:
        """Determine the username for a file server pod.

        Parameters
        ----------
        pod
            Pod object.

        Returns
        -------
        str
            Username corresponding to that file server pod, or `None` if no
            username information could be found.
        """
        labels = pod.metadata.labels
        if labels and "nublado.lsst.io/user" in labels:
            return labels["nublado.lsst.io/user"]
        elif m := re.match("^(.*)-fs$", pod.metadata.name):
            return m.group(1)
        else:
            return None

    def is_valid(self, username: str, state: FileserverStateObjects) -> bool:
        """Determine whether a running fileserver is valid.

        Parameters
        ----------
        username
            Username the fileserver is for, used for logging.
        state
            Kubernetes objects making up the fileserver.

        Returns
        -------
        bool
            `True` if the fileserver is valid and running, `False` otherwise.
        """
        logger = self._logger.bind(user=username)
        if not state.pod:
            logger.info("File server pod does not exist")
            return False
        pod = state.pod
        if not pod.status:
            logger.warning("Pod has no status", name=pod.metadata.name)
            return False
        if pod.status.phase != "Running":
            msg = "File server pod is not running"
            logger.info(msg, name=pod.metadata.name, status=pod.status.phase)
            return False
        if not state.ingress:
            logger.info("File server ingress does not exist")
            return False
        if not ingress_has_ip_address(state.ingress):
            name = state.ingress.metadata.name
            logger.info("Ingress does not have IP address", name=name)
            return False
        logger.debug("File server is running")
        return True

    def _build_metadata(self, username: str) -> V1ObjectMeta:
        """Construct the metadata for an object.

        This adds some standard labels and annotations providing Nublado
        metadata and telling Argo CD how to handle this object.
        """
        name = self.build_name(username)
        labels = {
            "nublado.lsst.io/category": "fileserver",
            "nublado.lsst.io/user": username,
        }
        if self._config.application:
            labels["argocd.argoproj.io/instance"] = self._config.application
        annotations = ARGO_CD_ANNOTATIONS.copy()
        return V1ObjectMeta(name=name, labels=labels, annotations=annotations)

    def _build_ingress(self, username: str) -> dict[str, Any]:
        """Construct ``GafaelfawrIngress`` object for the fileserver."""
        host = urlparse(self._base_url).hostname
        metadata = self._build_metadata(username).to_dict(serialize=True)
        path = {
            "path": f"/files/{username}",
            "pathType": "Prefix",
            "backend": {
                "service": {
                    "name": self.build_name(username),
                    "port": {"number": 8000},
                }
            },
        }
        return {
            "apiVersion": "gafaelfawr.lsst.io/v1alpha1",
            "kind": "GafaelfawrIngress",
            "metadata": metadata,
            "config": {
                "baseUrl": self._base_url,
                "scopes": {"all": ["exec:notebook"]},
                "loginRedirect": False,
                "authType": "basic",
            },
            "template": {
                "metadata": {
                    "name": metadata["name"],
                    "labels": {
                        "nublado.lsst.io/category": "fileserver",
                        "nublado.lsst.io/user": username,
                    },
                },
                "spec": {"rules": [{"host": host, "http": {"paths": [path]}}]},
            },
        }

    def _build_job(self, user: UserInfo) -> V1Job:
        """Construct the job for a fileserver."""
        volume_data = self._volume_builder.build_mounted_volumes(
            user.username, self._volumes, prefix="/mnt"
        )
        url = f"{self._config.path_prefix}/files/{user.username}"
        resources = self._config.resources
        timeout = str(int(self._config.idle_timeout.total_seconds()))

        # Specification for the user's container.
        container = V1Container(
            name="fileserver",
            env=[
                V1EnvVar(name="WORBLEHAT_BASE_HREF", value=url),
                V1EnvVar(name="WORBLEHAT_TIMEOUT", value=timeout),
                V1EnvVar(name="WORBLEHAT_DIR", value="/mnt"),
            ],
            image=f"{self._config.image.repository}:{self._config.image.tag}",
            image_pull_policy=self._config.image.pull_policy.value,
            ports=[V1ContainerPort(container_port=8000, name="http")],
            resources=resources.to_kubernetes() if resources else None,
            security_context=V1SecurityContext(
                allow_privilege_escalation=False,
                read_only_root_filesystem=True,
            ),
            volume_mounts=[v.volume_mount for v in volume_data],
        )

        # Build the pod specification itself.
        metadata = self._build_metadata(user.username)
        return V1Job(
            metadata=metadata,
            spec=V1JobSpec(
                template=V1PodTemplateSpec(
                    metadata=V1ObjectMeta(
                        name=metadata.name,
                        labels={
                            "nublado.lsst.io/category": "fileserver",
                            "nublado.lsst.io/user": user.username,
                        },
                    ),
                    spec=V1PodSpec(
                        containers=[container],
                        restart_policy="Never",
                        security_context=V1PodSecurityContext(
                            run_as_user=user.uid,
                            run_as_group=user.gid,
                            run_as_non_root=True,
                            supplemental_groups=[x.id for x in user.groups],
                        ),
                        volumes=[v.volume for v in volume_data],
                    ),
                )
            ),
        )

    def _build_service(self, username: str) -> V1Service:
        """Construct the service for a fileserver."""
        return V1Service(
            metadata=self._build_metadata(username),
            spec=V1ServiceSpec(
                ports=[V1ServicePort(port=8000, target_port=8000)],
                selector={
                    "nublado.lsst.io/category": "fileserver",
                    "nublado.lsst.io/user": username,
                },
            ),
        )
