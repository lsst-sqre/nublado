"""Construction of Kubernetes objects for user migration pod."""

from kubernetes_asyncio.client import (
    V1Container,
    V1EnvVar,
    V1ObjectMeta,
    V1PersistentVolumeClaim,
    V1Pod,
    V1PodSecurityContext,
    V1PodSpec,
    V1SecurityContext,
)
from structlog.stdlib import BoundLogger

from ...config import Config, PVCVolumeSource
from ...constants import ARGO_CD_ANNOTATIONS
from ...models.domain.migrator import MigratorObjects, build_migrator_pod_name
from ._introspect import _introspect_container
from .lab import LabBuilder
from .volumes import VolumeBuilder

__all__ = ["MigratorBuilder"]


class MigratorBuilder:
    """Construct Kubernetes objects for user migrator pod for a particular
    pair of users.

    Parameters
    ----------
    config
        Nublado configuration, used for home volumes and pod resources.
    lab_builder
        Builder for this RSP's lab objects (used for home volumes).
    logger
        Logger to use.
    """

    def __init__(
        self, config: Config, lab_builder: LabBuilder, logger: BoundLogger
    ) -> None:
        self._lab_config = config.lab
        self._fsadmin_config = config.fsadmin
        self._lab_builder = lab_builder
        self._logger = logger
        self._volume_builder = VolumeBuilder()
        self._container = _introspect_container(logger)

    def build(self, old_user: str, new_user: str) -> MigratorObjects:
        """Construct the objects that make up migrator for these users.

        Parameters
        ----------
        old_user
            Username for source user to copy from.
        new_user
            Username for target user to copy to.

        Returns
        -------
        MigratorObjects
            Kubernetes objects for the migrator environment.
        """
        return MigratorObjects(
            pvcs=self._build_pvcs(old_user, new_user),
            pod=self._build_pod(old_user, new_user),
        )

    def _build_metadata(self, name: str, suffix: str = "") -> V1ObjectMeta:
        """Construct the metadata for an object.

        This adds some standard labels and annotations providing Nublado
        metadata and telling Argo CD how to handle this object.
        """
        labels = {"nublado.lsst.io/category": "migrator"}
        annotations = ARGO_CD_ANNOTATIONS.copy()
        return V1ObjectMeta(
            name=name + suffix, labels=labels, annotations=annotations
        )

    def _build_pod(self, old_user: str, new_user: str) -> V1Pod:
        """Construct the pod for fsadmin."""
        pod_name = build_migrator_pod_name(old_user, new_user)
        # Volumes and volume_mounts should each be a one-item list
        volumes = [
            x
            for x in self._lab_config.volumes
            if x.name == self._lab_config.home_volume_name
        ]
        volume_mounts = [
            x
            for x in self._lab_config.volume_mounts
            if x.volume_name == self._lab_config.home_volume_name
        ]
        # Force mounts to read/write
        for vol in volume_mounts:
            vol.read_only = False
        volume_list = self._volume_builder.build_volumes(
            (v for v in volumes), pvc_prefix=pod_name
        )
        mounts = self._volume_builder.build_mounts(volume_mounts)
        resources = self._fsadmin_config.resources

        # Specification for the migrator container.
        container = V1Container(
            name=pod_name,
            command=["nublado", "migrator"],
            env=self._build_env(old_user, new_user),
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
        metadata = self._build_metadata(name=pod_name)
        if self._fsadmin_config.extra_annotations:
            metadata.annotations.update(self._fsadmin_config.extra_annotations)
        affinity = None
        if self._fsadmin_config.affinity:
            affinity = self._fsadmin_config.affinity.to_kubernetes()
        node_selector = None
        if self._fsadmin_config.node_selector:
            node_selector = self._fsadmin_config.node_selector.copy()
        tolerations = [
            t.to_kubernetes() for t in self._fsadmin_config.tolerations
        ]
        return V1Pod(
            metadata=metadata,
            spec=V1PodSpec(
                affinity=affinity,
                containers=[container],
                node_selector=node_selector,
                restart_policy="Never",
                security_context=V1PodSecurityContext(run_as_non_root=False),
                tolerations=tolerations,
                volumes=volume_list,
            ),
        )

    def _build_env(self, old_user: str, new_user: str) -> list[V1EnvVar]:
        return [
            V1EnvVar(name="NUBLADO_OLD_USER", value=old_user),
            V1EnvVar(name="NUBLADO_NEW_USER", value=new_user),
            V1EnvVar(
                name="NUBLADO_OLD_HOMEDIR",
                value=self._lab_builder.build_home_directory(old_user),
            ),
            V1EnvVar(
                name="NUBLADO_NEW_HOMEDIR",
                value=self._lab_builder.build_home_directory(new_user),
            ),
        ]

    def _build_pvcs(
        self, old_user: str, new_user: str
    ) -> list[V1PersistentVolumeClaim]:
        """Construct the persistent volume claims for migrator."""
        volumes = [
            x
            for x in self._lab_config.volumes
            if x.name == self._lab_config.home_volume_name
        ]
        pvcs: list[V1PersistentVolumeClaim] = []
        for volume in volumes:
            if not isinstance(volume.source, PVCVolumeSource):
                continue
            suffix = f"-pvc-{volume.name}"
            pvc = V1PersistentVolumeClaim(
                metadata=self._build_metadata(
                    name=build_migrator_pod_name(old_user, new_user),
                    suffix=suffix,
                ),
                spec=volume.source.to_kubernetes_spec(),
            )
            pvcs.append(pvc)
        return pvcs
