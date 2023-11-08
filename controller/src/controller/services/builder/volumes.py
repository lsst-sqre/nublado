"""Construction of Kubernetes objects for volumes and volume mounts."""

from __future__ import annotations

from kubernetes_asyncio.client import (
    V1HostPathVolumeSource,
    V1NFSVolumeSource,
    V1PersistentVolumeClaimVolumeSource,
    V1Volume,
    V1VolumeMount,
)

from ...config import (
    HostPathVolumeSource,
    LabVolume,
    NFSVolumeSource,
    PVCVolumeSource,
)
from ...models.domain.volumes import MountedVolume

__all__ = ["VolumeBuilder"]


class VolumeBuilder:
    """Construct Kubernetes objects for volumes and volume mounts.

    This is broken into its own class since it is used when constructing both
    labs and fileservers.
    """

    def build_mounted_volumes(
        self, username: str, volumes: list[LabVolume], prefix: str = ""
    ) -> list[MountedVolume]:
        """Construct volumes and mounts for volumes in the lab configuration.

        Parameters
        ----------
        username
            Name of user this lab is for, used to name the PVC objects.
        volumes
            Configured volumes.
        prefix
            Prefix to prepend to all mount paths, if given.

        Returns
        -------
        list of MountedVolume
            List of volumes and mounts.
        """
        volume_objects = self._build_volumes(username, volumes)
        mounts = self._build_mounts(volumes, prefix)
        return [
            MountedVolume(volume=v, volume_mount=m)
            for v, m in zip(volume_objects, mounts, strict=True)
        ]

    def _build_volume_name(self, volume: LabVolume) -> str:
        """Construct the name of the volume resource."""
        return volume.container_path.replace("/", "-")[1:].lower()

    def _build_volumes(
        self, username: str, volumes: list[LabVolume]
    ) -> list[V1Volume]:
        """Construct volumes and mounts for volumes in the lab configuration.

        Parameters
        ----------
        username
            Name of user this lab is for, used to name the PVC objects.
        volumes
            Configured volumes.

        Returns
        -------
        list of kubernetes_asyncio.client.V1Volume
            List of volumes and mounts.
        """
        results = []
        pvc_count = 1
        for spec in volumes:
            name = self._build_volume_name(spec)
            match spec.source:
                case HostPathVolumeSource() as source:
                    host_path = V1HostPathVolumeSource(path=source.path)
                    volume = V1Volume(name=name, host_path=host_path)
                case NFSVolumeSource() as source:
                    volume = V1Volume(
                        name=name,
                        nfs=V1NFSVolumeSource(
                            path=source.server_path,
                            read_only=spec.read_only,
                            server=source.server,
                        ),
                    )
                case PVCVolumeSource():
                    claim = V1PersistentVolumeClaimVolumeSource(
                        claim_name=f"{username}-nb-pvc-{pvc_count}",
                        read_only=spec.read_only,
                    )
                    volume = V1Volume(name=name, persistent_volume_claim=claim)
                    pvc_count += 1
            results.append(volume)
        return results

    def _build_mounts(
        self, volumes: list[LabVolume], prefix: str = ""
    ) -> list[V1VolumeMount]:
        """Construct volume mounts for configured volumes.

        Parameters
        ----------
        volumes
            Configured volumes.
        prefix
            Prefix to prepend to all mount paths, if given.

        Returns
        -------
        list of kubernetes_asyncio.client.V1VolumeMount
            List of volumes and mounts.
        """
        return [
            V1VolumeMount(
                name=self._build_volume_name(v),
                mount_path=prefix + v.container_path,
                sub_path=v.sub_path,
                read_only=v.read_only,
            )
            for v in volumes
        ]
