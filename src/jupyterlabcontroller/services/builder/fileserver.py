"""Construction of Kubernetes objects for user fileservers."""

from __future__ import annotations

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
    V1SecurityContext,
    V1Service,
    V1ServicePort,
    V1ServiceSpec,
)

from ...config import FileserverConfig, LabVolume
from ...constants import ARGO_CD_ANNOTATIONS
from ...models.domain.fileserver import FileserverObjects
from ...models.v1.lab import UserInfo
from .volumes import VolumeBuilder

__all__ = ["FileserverBuilder"]


class FileserverBuilder:
    """Construct Kubernetes objects for user fileservers.

    Parameters
    ----------
    config
        Fileserver configuration.
    instance_url
        Base URL for this Notebook Aspect instance.
    volumes
        Volumes to mount in the user's fileserver.
    """

    def __init__(
        self,
        config: FileserverConfig,
        instance_url: str,
        volumes: list[LabVolume],
    ) -> None:
        self._config = config
        self._instance_url = instance_url
        self._volumes = volumes
        self._volume_builder = VolumeBuilder()

    def build_fileserver(self, user: UserInfo) -> FileserverObjects:
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
            ingress=self._build_fileserver_ingress(user.username),
            service=self._build_fileserver_service(user.username),
            job=self._build_fileserver_job(user),
        )

    def build_fileserver_name(self, username: str) -> str:
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

    def _build_metadata(self, username: str) -> V1ObjectMeta:
        """Construct the metadata for an object.

        This adds some standard labels and annotations providing Nublado
        metadata and telling Argo CD how to handle this object.
        """
        name = self.build_fileserver_name(username)
        labels = {
            "nublado.lsst.io/category": "fileserver",
            "nublado.lsst.io/user": username,
        }
        if self._config.application:
            labels["argocd.argoproj.io/instance"] = self._config.application
        annotations = ARGO_CD_ANNOTATIONS.copy()
        return V1ObjectMeta(name=name, labels=labels, annotations=annotations)

    def _build_fileserver_ingress(self, username: str) -> dict[str, Any]:
        """Construct ``GafaelfawrIngress`` object for the fileserver."""
        host = urlparse(self._instance_url).hostname
        metadata = self._build_metadata(username).to_dict(serialize=True)
        path = {
            "path": f"/files/{username}",
            "pathType": "Prefix",
            "backend": {
                "service": {
                    "name": self.build_fileserver_name(username),
                    "port": {"number": 8000},
                }
            },
        }
        return {
            "apiVersion": "gafaelfawr.lsst.io/v1alpha1",
            "kind": "GafaelfawrIngress",
            "metadata": metadata,
            "config": {
                "baseUrl": self._instance_url,
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

    def _build_fileserver_job(self, user: UserInfo) -> V1Job:
        """Construct the job for a fileserver."""
        volume_data = self._volume_builder.build_mounted_volumes(
            user.username, self._volumes, prefix="/mnt"
        )
        url = f"{self._config.path_prefix}/files/{user.username}"
        resources = self._config.resources
        timeout = str(self._config.timeout)

        # Specification for the user's container.
        container = V1Container(
            name="fileserver",
            env=[
                V1EnvVar(name="WORBLEHAT_BASE_HREF", value=url),
                V1EnvVar(name="WORBLEHAT_TIMEOUT", value=timeout),
                V1EnvVar(name="WORBLEHAT_DIR", value="/mnt"),
            ],
            image=f"{self._config.image}:{self._config.tag}",
            image_pull_policy=self._config.pull_policy.value,
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

    def _build_fileserver_service(self, username: str) -> V1Service:
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
