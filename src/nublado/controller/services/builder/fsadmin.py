"""Construction of Kubernetes objects for user fileservers."""

from kubernetes_asyncio.client import (
    V1Container,
    V1ObjectMeta,
    V1PersistentVolumeClaim,
    V1Pod,
    V1PodSecurityContext,
    V1PodSpec,
    V1SecurityContext,
)
from structlog.stdlib import BoundLogger

from ...config import (
    FSAdminConfig,
    PVCVolumeSource,
    VolumeConfig,
    VolumeMountConfig,
)
from ...constants import ARGO_CD_ANNOTATIONS
from ...models.domain.fsadmin import (
    FSAdminObjects,
)
from ._introspect import _introspect_container
from .volumes import VolumeBuilder

__all__ = ["FSAdminBuilder"]


class FSAdminBuilder:
    """Construct Kubernetes objects for file system administrative pods.

    Parameters
    ----------
    config
        Administrative pod configuration.
    volumes
        Volumes to mount in the file system admin pod.
    volume_mounts
        How to mount the specified volumes.
    logger
        Logger to use.
    """

    def __init__(
        self,
        config: FSAdminConfig,
        volumes: list[VolumeConfig],
        volume_mounts: list[VolumeMountConfig],
        logger: BoundLogger,
    ) -> None:
        self._config = config
        self._volumes = volumes
        self._volume_mounts = volume_mounts
        self._logger = logger
        self._volume_builder = VolumeBuilder()
        self._container = _introspect_container(logger)

    def build(self) -> FSAdminObjects:
        """Construct the objects that make up fsadmin.

        Returns
        -------
        FSAdminObjects
            Kubernetes objects for the fsadmin environment.
        """
        return FSAdminObjects(pvcs=self._build_pvcs(), pod=self._build_pod())

    def _build_metadata(self, name: str, suffix: str = "") -> V1ObjectMeta:
        """Construct the metadata for an object.

        This adds some standard labels and annotations providing Nublado
        metadata and telling Argo CD how to handle this object.
        """
        labels = {"nublado.lsst.io/category": "fsadmin"}
        annotations = ARGO_CD_ANNOTATIONS.copy()
        return V1ObjectMeta(
            name=name + suffix,
            labels=labels,
            annotations=annotations,
        )

    def _build_pod(self) -> V1Pod:
        """Construct the pod for fsadmin."""
        # Glue in extra volumes.
        volumes = list(self._volumes)
        volumes.extend(self._config.extra_volumes)
        volume_mounts = list(self._volume_mounts)
        volume_mounts.extend(self._config.extra_volume_mounts)
        # Force all mounts to read/write
        for vol in volume_mounts:
            vol.read_only = False
        wanted_volumes = {m.volume_name for m in volume_mounts}
        volume_list = self._volume_builder.build_volumes(
            (v for v in volumes if v.name in wanted_volumes),
            pvc_prefix=self._config.pod_name,
        )
        prefix = self._config.mount_prefix or ""
        mounts = self._volume_builder.build_mounts(
            volume_mounts, prefix=prefix
        )
        resources = self._config.resources

        # Specification for the fsadmin container.
        container = V1Container(
            name=self._config.pod_name,
            command=["tail", "-f", "/dev/null"],
            image=f"{self._container.repository}:{self._container.tag}",
            image_pull_policy=self._container.pull_policy.value,
            resources=resources.to_kubernetes() if resources else None,
            security_context=V1SecurityContext(
                privileged=True,
                run_as_non_root=False,
                run_as_user=0,
                run_as_group=0,
            ),
            volume_mounts=mounts,
        )

        # Build the pod specification itself.
        metadata = self._build_metadata(name=self._config.pod_name)
        if self._config.extra_annotations:
            metadata.annotations.update(self._config.extra_annotations)
        affinity = None
        if self._config.affinity:
            affinity = self._config.affinity.to_kubernetes()
        node_selector = None
        if self._config.node_selector:
            node_selector = self._config.node_selector.copy()
        tolerations = [t.to_kubernetes() for t in self._config.tolerations]
        return V1Pod(
            metadata=metadata,
            spec=V1PodSpec(
                affinity=affinity,
                containers=[container],
                node_selector=node_selector,
                restart_policy="Never",
                security_context=V1PodSecurityContext(
                    run_as_non_root=False,
                ),
                tolerations=tolerations,
                volumes=volume_list,
            ),
        )

    def _build_pvcs(self) -> list[V1PersistentVolumeClaim]:
        """Construct the persistent volume claims for fsadmin."""
        volume_names = {m.volume_name for m in self._volume_mounts}
        volumes = (v for v in self._volumes if v.name in volume_names)
        pvcs: list[V1PersistentVolumeClaim] = []
        for volume in volumes:
            if not isinstance(volume.source, PVCVolumeSource):
                continue
            suffix = f"-pvc-{volume.name}"
            pvc = V1PersistentVolumeClaim(
                metadata=self._build_metadata(
                    name=self._config.pod_name, suffix=suffix
                ),
                spec=volume.source.to_kubernetes_spec(),
            )
            pvcs.append(pvc)
        return pvcs
