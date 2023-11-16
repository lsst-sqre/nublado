"""Construction of Kubernetes objects for volumes and volume mounts."""

from __future__ import annotations

from collections.abc import Iterable

from kubernetes_asyncio.client import (
    V1HostPathVolumeSource,
    V1NFSVolumeSource,
    V1PersistentVolumeClaimVolumeSource,
    V1Volume,
    V1VolumeMount,
)

from ...config import (
    HostPathVolumeSource,
    NFSVolumeSource,
    PVCVolumeSource,
    VolumeConfig,
    VolumeMountConfig,
)

__all__ = ["VolumeBuilder"]


class VolumeBuilder:
    """Construct Kubernetes objects for volumes and volume mounts.

    This is broken into its own class since it is used when constructing both
    labs and fileservers.
    """

    def build_mounts(
        self, mounts: Iterable[VolumeMountConfig], prefix: str = ""
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
                name=m.volume_name,
                mount_path=prefix + m.container_path,
                sub_path=m.sub_path,
                read_only=m.read_only,
            )
            for m in mounts
        ]

    def build_volumes(
        self, volumes: Iterable[VolumeConfig], pvc_prefix: str
    ) -> list[V1Volume]:
        """Construct Kubernetes ``V1Volume`` objects for configured volumes.

        Parameters
        ----------
        volumes
            Configured volumes.
        pvc_prefx
            Prefix to add to the names of persistent volume claims. The name
            of the claim will be followed by ``-pvc-`` and the name of the
            volume.

        Returns
        -------
        list of kubernetes_asyncio.client.V1Volume
            List of Kubernetes ``V1Volume`` objects.
        """
        results = []
        for spec in volumes:
            match spec.source:
                case HostPathVolumeSource() as source:
                    host_path = V1HostPathVolumeSource(path=source.path)
                    volume = V1Volume(name=spec.name, host_path=host_path)
                case NFSVolumeSource() as source:
                    volume = V1Volume(
                        name=spec.name,
                        nfs=V1NFSVolumeSource(
                            path=source.server_path,
                            read_only=source.read_only,
                            server=source.server,
                        ),
                    )
                case PVCVolumeSource() as source:
                    claim = V1PersistentVolumeClaimVolumeSource(
                        claim_name=f"{pvc_prefix}-pvc-{spec.name}",
                        read_only=source.read_only,
                    )
                    volume = V1Volume(
                        name=spec.name, persistent_volume_claim=claim
                    )
            results.append(volume)
        return results
