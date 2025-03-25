"""Construction of Kubernetes objects for user lab environments."""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path

from kubernetes_asyncio.client import (
    V1Capabilities,
    V1ConfigMap,
    V1ConfigMapEnvSource,
    V1ConfigMapVolumeSource,
    V1Container,
    V1ContainerPort,
    V1DownwardAPIVolumeFile,
    V1DownwardAPIVolumeSource,
    V1EmptyDirVolumeSource,
    V1EnvFromSource,
    V1EnvVar,
    V1EnvVarSource,
    V1KeyToPath,
    V1LabelSelector,
    V1LocalObjectReference,
    V1Namespace,
    V1NetworkPolicy,
    V1NetworkPolicyIngressRule,
    V1NetworkPolicyPeer,
    V1NetworkPolicyPort,
    V1NetworkPolicySpec,
    V1ObjectFieldSelector,
    V1ObjectMeta,
    V1PersistentVolumeClaim,
    V1Pod,
    V1PodSecurityContext,
    V1PodSpec,
    V1ResourceFieldSelector,
    V1ResourceQuota,
    V1ResourceQuotaSpec,
    V1Secret,
    V1SecretKeySelector,
    V1SecretVolumeSource,
    V1SecurityContext,
    V1Service,
    V1ServicePort,
    V1ServiceSpec,
    V1Volume,
    V1VolumeMount,
)
from structlog.stdlib import BoundLogger

from ...config import (
    LabConfig,
    PVCVolumeSource,
    TmpSource,
    UserHomeDirectorySchema,
)
from ...constants import ARGO_CD_ANNOTATIONS, MEMORY_TO_TMP_SIZE_RATIO
from ...models.domain.gafaelfawr import GafaelfawrUserInfo, UserGroup
from ...models.domain.lab import LabObjectNames, LabObjects, LabStateObjects
from ...models.domain.rspimage import RSPImage
from ...models.domain.volumes import MountedVolume
from ...models.v1.lab import (
    LabOptions,
    LabResources,
    LabSize,
    LabSpecification,
    LabState,
    LabStatus,
    ResourceQuantity,
    UserInfo,
)
from .volumes import VolumeBuilder

__all__ = ["LabBuilder"]


class LabBuilder:
    """Construct Kubernetes objects for user lab environments.

    Parameters
    ----------
    config
        Lab configuration.
    base_url
        Base URL for this Notebook Aspect instance.
    logger
        Logger to use.
    """

    def __init__(
        self, config: LabConfig, base_url: str, logger: BoundLogger
    ) -> None:
        self._config = config
        self._base_url = base_url
        self._logger = logger
        self._volume_builder = VolumeBuilder()

    def build_internal_url(self, username: str, env: dict[str, str]) -> str:
        """Determine the URL of a newly-spawned lab.

        The hostname and port are fixed to match the Kubernetes ``Service`` we
        create, but the local part is normally determined by an environment
        variable passed from JupyterHub.

        Parameters
        ----------
        username
            Username of lab user.
        env
            Environment variables from JupyterHub.

        Returns
        -------
        str
            URL of the newly-spawned lab.
        """
        namespace = f"{self._config.namespace_prefix}-{username}"
        path = env["JUPYTERHUB_SERVICE_PREFIX"]
        return f"http://lab.{namespace}:8888" + path

    def build_object_names(self, username: str) -> LabObjectNames:
        """Construct the names of the critical lab objects for a user.

        This is used to construct names to pass to the lab storage layer to
        identify the objects used to get lab status or reconcile lab state.

        Parameters
        ----------
        username
            Username of the user to construct object names for.

        Returns
        -------
        LabObjectNames
            Names of objects for that user.
        """
        return LabObjectNames(
            username=username,
            namespace=f"{self._config.namespace_prefix}-{username}",
            env_config_map=f"{username}-nb-env",
            quota=f"{username}-nb",
            pod=f"{username}-nb",
        )

    def build_lab(
        self,
        *,
        user: GafaelfawrUserInfo,
        lab: LabSpecification,
        image: RSPImage,
        secrets: dict[str, str],
        pull_secret: V1Secret | None = None,
    ) -> LabObjects:
        """Construct the objects that make up a user's lab.

        Parameters
        ----------
        username
            Username of the user.
        lab
            Specification of the lab requested.
        image
            Image to use for the lab.
        secrets
            Dictionary of secrets to expose to the lab.
        pull_secret
            Optional pull secret for the lab pod.

        Returns
        -------
        LabObjects
            Kubernetes objects that make up the user's lab.
        """
        return LabObjects(
            namespace=self._build_namespace(user.username),
            env_config_map=self._build_env_config_map(user, lab, image),
            config_maps=self._build_config_maps(user),
            network_policy=self._build_network_policy(user.username),
            pvcs=self._build_pvcs(user.username),
            quota=self._build_quota(user),
            secrets=self._build_secrets(user.username, secrets, pull_secret),
            service=self._build_service(user.username),
            pod=self._build_pod(user, lab, image),
        )

    async def recreate_lab_state(
        self, username: str, objects: LabStateObjects | None
    ) -> LabState | None:
        """Recreate user lab state from Kubernetes.

        Given the critical objects from a user's lab, reconstruct the user's
        lab state. This is used during reconciliation and allows us to
        recreate internal state from whatever currently exists in Kubernetes
        when the lab controller is restarted.

        Parameters
        ----------
        username
            User whose lab state should be recreated.
        objects
            Objects for that user's lab, or `None` if any required objects
            were not found.

        Returns
        -------
        LabState or None
            Recreated lab state, or `None` if the user's lab environment did
            not exist or could not be parsed.

        Raises
        ------
        KubernetesError
            Raised if Kubernetes API calls fail for reasons other than the
            resources not existing.
        """
        if not objects:
            return None
        logger = self._logger.bind(user=username)

        # Find the lab container.
        lab_container = None
        for container in objects.pod.spec.containers:
            if container.name == "notebook":
                lab_container = container
                break
        if not lab_container:
            error = 'No container named "notebook"'
            logger.error("Invalid lab environment", error=error)
            return None

        # Gather the necessary information from the pod. If anything is
        # missing or in an unexpected format, log an error and return None.
        env = objects.env_config_map.data
        pod = objects.pod
        try:
            resources = LabResources(
                limits=ResourceQuantity(
                    cpu=float(env["CPU_LIMIT"]),
                    memory=int(env["MEM_LIMIT"]),
                ),
                requests=ResourceQuantity(
                    cpu=float(env["CPU_GUARANTEE"]),
                    memory=int(env["MEM_GUARANTEE"]),
                ),
            )
            options = LabOptions(
                image=env["JUPYTER_IMAGE_SPEC"],
                size=self._recreate_size(resources),
                enable_debug=env.get("DEBUG", "FALSE") == "TRUE",
                reset_user_env=env.get("RESET_USER_ENV", "FALSE") == "TRUE",
            )
            user = UserInfo(
                username=username,
                name=pod.metadata.annotations.get("nublado.lsst.io/user-name"),
                uid=lab_container.security_context.run_as_user,
                gid=lab_container.security_context.run_as_group,
                groups=self._recreate_groups(pod),
            )
            return LabState(
                user=user,
                options=options,
                status=LabStatus.from_phase(pod.status.phase),
                internal_url=self.build_internal_url(username, env),
                resources=resources,
                quota=self._recreate_quota(objects.quota),
            )
        except Exception:
            logger.exception("Invalid lab environment", error=error)
            return None

    def _build_home_directory(self, username: str) -> str:
        """Construct the home directory path for a user."""
        prefix = self._config.homedir_prefix
        match self._config.homedir_schema:
            case UserHomeDirectorySchema.USERNAME:
                home = prefix + f"/{username}"
            case UserHomeDirectorySchema.INITIAL_THEN_USERNAME:
                home = prefix + f"/{username[0]}/{username}"
        if self._config.homedir_suffix:
            home += "/" + self._config.homedir_suffix
        return home

    def _build_metadata(self, name: str, username: str) -> V1ObjectMeta:
        """Construct the metadata for an object.

        This adds some standard labels and annotations providing Nublado
        metadata and telling Argo CD how to handle this object.
        """
        labels = {
            "nublado.lsst.io/category": "lab",
            "nublado.lsst.io/user": username,
        }
        if self._config.application:
            labels["argocd.argoproj.io/instance"] = self._config.application
        annotations = ARGO_CD_ANNOTATIONS.copy()
        return V1ObjectMeta(name=name, labels=labels, annotations=annotations)

    def _build_namespace(self, username: str) -> V1Namespace:
        """Construct the namespace object for a user's lab."""
        name = f"{self._config.namespace_prefix}-{username}"
        return V1Namespace(metadata=self._build_metadata(name, username))

    def _build_config_maps(
        self, user: GafaelfawrUserInfo
    ) -> list[V1ConfigMap]:
        """Build the config maps used by the user's lab pod."""
        config_maps = [self._build_nss_config_map(user)]
        if file_config_map := self._build_file_config_map(user.username):
            config_maps.append(file_config_map)
        return config_maps

    def _build_env_config_map(
        self, user: GafaelfawrUserInfo, lab: LabSpecification, image: RSPImage
    ) -> V1ConfigMap:
        """Build the config map holding the lab environment variables."""
        env = lab.env.copy()

        # Add additional environment variables based on user options.
        if lab.options.enable_debug:
            env["DEBUG"] = "TRUE"
        if lab.options.reset_user_env:
            env["RESET_USER_ENV"] = "TRUE"

        # Add standard environment variables.
        size = self._config.get_size_definition(lab.options.size)
        activity = str(int(self._config.activity_interval.total_seconds()))
        resources = size.to_lab_resources()
        env.update(
            {
                # We would like to deprecate this, following KubeSpawner, but
                # it's currently used by the lab extensions.
                "JUPYTER_IMAGE": image.reference_with_digest,
                # Image data for display frame.
                "JUPYTER_IMAGE_SPEC": image.reference_with_digest,
                "IMAGE_DESCRIPTION": image.display_name,
                "IMAGE_DIGEST": image.digest,
                # Container data for display frame.
                "CONTAINER_SIZE": str(size),
                # Normally set by JupyterHub so keep compatibility.
                "CPU_GUARANTEE": str(resources.requests.cpu),
                "CPU_LIMIT": str(resources.limits.cpu),
                "MEM_GUARANTEE": str(resources.requests.memory),
                "MEM_LIMIT": str(resources.limits.memory),
                # Activity reporting interval.
                "JUPYTERHUB_ACTIVITY_INTERVAL": activity,
                # Used by code running in the lab to find other services.
                "EXTERNAL_INSTANCE_URL": self._base_url,
                # Information about where our Lab config, runtime-info
                # mounts can be found, and command to launch the lab
                "JUPYTERLAB_CONFIG_DIR": self._config.jupyterlab_config_dir,
                "JUPYTERLAB_START_COMMAND": shlex.join(
                    self._config.lab_start_command
                ),
                "NUBLADO_RUNTIME_MOUNTS_DIR": self._config.runtime_mounts_dir,
            }
        )

        # Finally, add any environment variable settings from our
        # configuration. Anything set here overrides anything the user sends
        # or anything we add internally.
        env.update(self._config.env)

        # Return the resulting ConfigMap.
        username = user.username
        return V1ConfigMap(
            metadata=self._build_metadata(f"{username}-nb-env", username),
            immutable=True,
            data=env,
        )

    def _build_file_config_map(self, username: str) -> V1ConfigMap | None:
        """Build the config map holding supplemental mounted files."""
        if not self._config.files:
            return None
        return V1ConfigMap(
            metadata=self._build_metadata(f"{username}-nb-files", username),
            immutable=True,
            data={
                re.sub(r"[_.]", "-", Path(k).name): v
                for k, v in self._config.files.items()
            },
        )

    def _build_nss_config_map(self, user: GafaelfawrUserInfo) -> V1ConfigMap:
        """Build the config map holding NSS files.

        The NSS ``ConfigMap`` provides the :file:`/etc/passwd` and
        :file`/etc/group` files for the running lab. These files are
        constructed by adding entries for the user and their groups to a base
        file in the Nublado controller configuration.
        """
        etc_passwd = self._config.nss.base_passwd
        etc_group = self._config.nss.base_group

        # Construct the user's /etc/passwd entry. Different sites use
        # different schemes for constructing the home directory path.
        homedir = self._build_home_directory(user.username)
        etc_passwd += (
            f"{user.username}:x:{user.uid}:{user.gid}:"
            f"{user.name}:{homedir}:/bin/bash\n"
        )

        # Construct the /etc/group entry by adding all groups that have GIDs.
        # Add the user as an additional member of their supplemental groups.
        for group in user.groups:
            if group.id == user.gid:
                etc_group += f"{group.name}:x:{group.id}:\n"
            else:
                etc_group += f"{group.name}:x:{group.id}:{user.username}\n"

        # Return the resulting ConfigMap.
        username = user.username
        return V1ConfigMap(
            metadata=self._build_metadata(f"{username}-nb-nss", username),
            immutable=True,
            data={"passwd": etc_passwd, "group": etc_group},
        )

    def _build_network_policy(self, username: str) -> V1NetworkPolicy:
        """Construct the network policy for a user's lab."""
        metadata = self._build_metadata(f"{username}-nb", username)
        lab_selector = V1LabelSelector(
            match_labels={
                "nublado.lsst.io/category": "lab",
                "nublado.lsst.io/user": username,
            }
        )
        hub_selector = V1LabelSelector(match_labels={"app": "jupyterhub"})
        ingress_rules = [
            V1NetworkPolicyPeer(namespace_selector=lab_selector),
            V1NetworkPolicyPeer(
                namespace_selector=V1LabelSelector(),
                pod_selector=hub_selector,
            ),
        ]
        return V1NetworkPolicy(
            metadata=metadata,
            spec=V1NetworkPolicySpec(
                policy_types=["Ingress"],
                pod_selector=lab_selector,
                ingress=[
                    V1NetworkPolicyIngressRule(
                        _from=ingress_rules,
                        ports=[V1NetworkPolicyPort(port=8888)],
                    ),
                ],
            ),
        )

    def _build_pvcs(self, username: str) -> list[V1PersistentVolumeClaim]:
        """Construct the persistent volume claims for a user's lab."""
        volume_names = {m.volume_name for m in self._config.volume_mounts}
        volumes = (v for v in self._config.volumes if v.name in volume_names)
        pvcs: list[V1PersistentVolumeClaim] = []
        for volume in volumes:
            if not isinstance(volume.source, PVCVolumeSource):
                continue
            name = f"{username}-nb-pvc-{volume.name}"
            pvc = V1PersistentVolumeClaim(
                metadata=self._build_metadata(name, username),
                spec=volume.source.to_kubernetes_spec(),
            )
            pvcs.append(pvc)
        return pvcs

    def _build_quota(self, user: GafaelfawrUserInfo) -> V1ResourceQuota | None:
        """Construct the namespace quota for a user's lab."""
        if not user.quota or not user.quota.notebook:
            return None
        memory_quota = int(user.quota.notebook.memory * 1024 * 1024 * 1024)
        username = user.username
        return V1ResourceQuota(
            metadata=self._build_metadata(f"{username}-nb", username),
            spec=V1ResourceQuotaSpec(
                hard={
                    "limits.cpu": str(user.quota.notebook.cpu),
                    "limits.memory": str(memory_quota),
                }
            ),
        )

    def _build_secrets(
        self, username: str, data: dict[str, str], pull_secret: V1Secret | None
    ) -> list[V1Secret]:
        """Construct the secrets for the user's lab."""
        secret = V1Secret(
            metadata=self._build_metadata(f"{username}-nb", username),
            data=data,
            immutable=True,
            type="Opaque",
        )
        secrets = [secret]
        if pull_secret:
            secret = V1Secret(
                metadata=self._build_metadata("pull-secret", username),
                data=pull_secret.data,
                immutable=True,
                type=pull_secret.type,
            )
            secrets.append(secret)
        return secrets

    def _build_service(self, username: str) -> V1Service:
        """Construct the service for a user's lab."""
        return V1Service(
            metadata=self._build_metadata("lab", username),
            spec=V1ServiceSpec(
                ports=[V1ServicePort(port=8888, target_port=8888)],
                selector={
                    "nublado.lsst.io/category": "lab",
                    "nublado.lsst.io/user": username,
                },
            ),
        )

    def _build_pod(
        self, user: GafaelfawrUserInfo, lab: LabSpecification, image: RSPImage
    ) -> V1Pod:
        """Construct the user's lab pod."""
        size = self._config.get_size_definition(lab.options.size)
        resources = size.to_lab_resources()

        # Construct the pull secrets.
        pull_secrets = None
        if self._config.pull_secret:
            pull_secrets = [V1LocalObjectReference(name="pull-secret")]

        # Construct the pod metadata.
        metadata = self._build_metadata(f"{user.username}-nb", user.username)
        metadata.annotations.update(self._build_pod_annotations(user))

        size = self._config.get_size_definition(lab.options.size)
        resources = size.to_lab_resources()

        # Gather the volume and volume mount definitions.
        mounted_volumes = [
            *self._build_pod_nss_volumes(user.username),
            *self._build_pod_file_volumes(user.username),
            self._build_pod_secret_volume(user.username),
            self._build_pod_env_volume(user.username),
            self._build_pod_tmp_volume(mem_size=resources.limits.memory),
            self._build_pod_downward_api_volume(user.username),
        ]
        volumes = self._build_pod_volumes(user.username, mounted_volumes)
        mounts = self._build_pod_volume_mounts(user.username, mounted_volumes)

        # Build the pod object itself.
        containers = self._build_pod_containers(user, mounts, resources, image)
        init_containers = self._build_pod_init_containers(user, resources)
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
                automount_service_account_token=False,
                containers=containers,
                image_pull_secrets=pull_secrets,
                init_containers=init_containers,
                node_selector=node_selector,
                restart_policy="OnFailure",
                security_context=V1PodSecurityContext(
                    supplemental_groups=user.supplemental_groups
                ),
                tolerations=tolerations,
                volumes=volumes,
            ),
        )

    def _build_pod_annotations(
        self, user: GafaelfawrUserInfo
    ) -> dict[str, str]:
        """Construct the annotations for the user's pod."""
        annotations = {"nublado.lsst.io/user-groups": user.groups_json()}
        if user.name is not None:
            annotations["nublado.lsst.io/user-name"] = user.name
        if self._config.extra_annotations:
            annotations.update(self._config.extra_annotations)
        return annotations

    def _build_pod_volumes(
        self, username: str, mounted_volumes: list[MountedVolume]
    ) -> list[V1Volume]:
        """Construct the volumes that will be mounted by the user's pod."""
        volumes = self._volume_builder.build_volumes(
            self._config.volumes, f"{username}-nb"
        )
        volumes.extend(v.volume for v in mounted_volumes)
        return volumes

    def _build_pod_volume_mounts(
        self, username: str, mounted_volumes: list[MountedVolume]
    ) -> V1VolumeMount:
        """Construct the volume mounts for the user's pod."""
        mounts = self._volume_builder.build_mounts(self._config.volume_mounts)
        mounts.extend(v.volume_mount for v in mounted_volumes)
        for spec in self._config.secrets:
            if not spec.path:
                continue
            mount = V1VolumeMount(
                mount_path=spec.path,
                name="secrets",
                read_only=True,
                sub_path=spec.secret_key,
            )
            mounts.append(mount)
        return mounts

    def _build_pod_config_map_volume(
        self, config_map: str, path: str
    ) -> MountedVolume:
        """Construct the mounted volume for a file from a ``ConfigMap``."""
        subpath = Path(path).name
        name = re.sub(r"[_.]", "-", subpath)
        key_to_path = V1KeyToPath(mode=0o0644, key=name, path=subpath)
        return MountedVolume(
            volume=V1Volume(
                name=name,
                config_map=V1ConfigMapVolumeSource(
                    name=config_map, items=[key_to_path]
                ),
            ),
            volume_mount=V1VolumeMount(
                mount_path=path,
                name=name,
                read_only=True,
                sub_path=subpath,
            ),
        )

    def _build_pod_file_volumes(self, username: str) -> list[MountedVolume]:
        """Construct the volumes that mount files from a ``ConfigMap``."""
        return [
            self._build_pod_config_map_volume(f"{username}-nb-files", f)
            for f in self._config.files
        ]

    def _build_pod_nss_volumes(self, username: str) -> list[MountedVolume]:
        """Construct the volumes for NSS files."""
        return [
            self._build_pod_config_map_volume(f"{username}-nb-nss", f)
            for f in ("/etc/passwd", "/etc/group")
        ]

    def _build_pod_secret_volume(self, username: str) -> MountedVolume:
        """Construct the volume that mounts the lab secrets.

        All secrets are mounted in the same directory. Secrets should
        preferably be referred to by that path, although we also support
        injecting them into environment variables and other paths for ease of
        transition.

        The mount path should be configurable, but isn't yet.

        Additional mount points for this volume are defined by
        `_build_pod_secret_volume_extra_mounts` and included in the volume
        mounts when constructing the pod.
        """
        secret_loc = f"{self._config.runtime_mounts_dir}/secrets"
        return MountedVolume(
            volume=V1Volume(
                name="secrets",
                secret=V1SecretVolumeSource(secret_name=f"{username}-nb"),
            ),
            volume_mount=V1VolumeMount(
                mount_path=secret_loc, name="secrets", read_only=True
            ),
        )

    def _build_pod_env_volume(self, username: str) -> MountedVolume:
        """Build the volume that mounts the environment inside the pod.

        It's not clear whether this is necessary, but we've been doing it for
        a while so removing this would potentially break backward
        compatibility.
        """
        env_path = f"{self._config.runtime_mounts_dir}/environment"
        return MountedVolume(
            volume=V1Volume(
                name="env",
                config_map=V1ConfigMapVolumeSource(name=f"{username}-nb-env"),
            ),
            volume_mount=V1VolumeMount(
                mount_path=env_path, name="env", read_only=True
            ),
        )

    def _build_pod_tmp_volume(self, mem_size: int) -> MountedVolume:
        """Build the volume that provides a writable tmpfs :file:`/tmp`.

        Note that it is the `Memory` medium setting that forces this to
        be tmpfs rather than ephemeral storage, and therefore usage will
        come from the pod memory allocation rather than disk space.
        """
        medium = None
        if self._config.tmp_source == TmpSource.MEMORY:
            medium = "Memory"
        return MountedVolume(
            volume=V1Volume(
                empty_dir=V1EmptyDirVolumeSource(
                    medium=medium,
                    size_limit=int(mem_size / MEMORY_TO_TMP_SIZE_RATIO),
                ),
                name="tmp",
            ),
            volume_mount=V1VolumeMount(
                mount_path="/tmp", name="tmp", read_only=False
            ),
        )

    def _build_pod_downward_api_volume(self, username: str) -> MountedVolume:
        """Build the volume that mounts downward API information.

        This is redundant with environment variables we set that contain the
        same information and therefore should ideally be removed, but we've
        been doing this for a while so removing it potentially breaks
        backwards compatibility.

        The mount path should be configurable, but isn't yet.
        """
        files = []
        fields = (
            "limits.cpu",
            "requests.cpu",
            "limits.memory",
            "requests.memory",
        )
        for field in fields:
            volume_file = V1DownwardAPIVolumeFile(
                resource_field_ref=V1ResourceFieldSelector(
                    container_name="notebook", resource=field
                ),
                path=field.replace(".", "_"),
            )
            files.append(volume_file)
        runtime_path = f"{self._config.runtime_mounts_dir}/runtime"
        return MountedVolume(
            volume=V1Volume(
                name="runtime",
                downward_api=V1DownwardAPIVolumeSource(items=files),
            ),
            volume_mount=V1VolumeMount(
                mount_path=runtime_path,
                name="runtime",
                read_only=True,
            ),
        )

    def _build_pod_init_containers(
        self, user: GafaelfawrUserInfo, resources: LabResources
    ) -> list[V1Container]:
        """Build init containers for the pod."""
        username = user.username
        as_root = V1SecurityContext(
            allow_privilege_escalation=True,
            privileged=True,
            read_only_root_filesystem=True,
            run_as_non_root=False,
            run_as_user=0,
        )
        as_user = V1SecurityContext(
            allow_privilege_escalation=False,
            capabilities=V1Capabilities(drop=["all"]),
            read_only_root_filesystem=True,
            run_as_non_root=True,
            run_as_user=user.uid,
            run_as_group=user.gid,
        )

        # Use the same environment ConfigMap as the notebook container since
        # it may contain other things we need for provisioning. Add
        # environment variables communicating the primary UID and GID, and
        # the user's home directory, which is our interface to provisioning
        # init containers.
        env_source = V1ConfigMapEnvSource(name=f"{username}-nb-env")
        home = self._build_home_directory(user.username)
        env = [
            V1EnvVar(name="NUBLADO_HOME", value=home),
            V1EnvVar(name="NUBLADO_UID", value=str(user.uid)),
            V1EnvVar(name="NUBLADO_GID", value=str(user.gid)),
        ]

        containers = []
        for spec in self._config.init_containers:
            mounts = self._volume_builder.build_mounts(spec.volume_mounts)
            container = V1Container(
                name=spec.name,
                env=env,
                env_from=[V1EnvFromSource(config_map_ref=env_source)],
                image=f"{spec.image.repository}:{spec.image.tag}",
                image_pull_policy=spec.image.pull_policy.value,
                resources=resources.to_kubernetes(),
                security_context=as_root if spec.privileged else as_user,
                volume_mounts=mounts,
            )
            containers.append(container)

        return containers

    def _build_pod_containers(
        self,
        user: GafaelfawrUserInfo,
        mounts: list[V1VolumeMount],
        resources: LabResources,
        image: RSPImage,
    ) -> V1PodSpec:
        """Construct the containers for the user's lab pod."""
        # Additional environment variables to set, layered on top of the env
        # ConfigMap. The ConfigMap holds public information known before the
        # lab is spawned; these environment variables hold everything else.
        env = [
            # User's Gafaelfawr token.
            V1EnvVar(
                name="ACCESS_TOKEN",
                value_from=V1EnvVarSource(
                    secret_key_ref=V1SecretKeySelector(
                        key="token", name=f"{user.username}-nb", optional=False
                    )
                ),
            ),
            # Node on which the pod is running.
            V1EnvVar(
                name="KUBERNETES_NODE_NAME",
                value_from=V1EnvVarSource(
                    field_ref=V1ObjectFieldSelector(field_path="spec.nodeName")
                ),
            ),
            # Deprecated version of KUBERNETES_NODE_NAME, used by lsst.rsp
            # 0.3.4 and earlier.
            V1EnvVar(
                name="K8S_NODE_NAME",
                value_from=V1EnvVarSource(
                    field_ref=V1ObjectFieldSelector(field_path="spec.nodeName")
                ),
            ),
        ]
        for spec in self._config.secrets:
            if not spec.env:
                continue
            selector = V1SecretKeySelector(
                key=spec.secret_key, name=f"{user.username}-nb", optional=False
            )
            source = V1EnvVarSource(secret_key_ref=selector)
            variable = V1EnvVar(name=spec.env, value_from=source)
            env.append(variable)

        # Specification for the user's container.
        env_source = V1ConfigMapEnvSource(name=f"{user.username}-nb-env")
        container = V1Container(
            name="notebook",
            args=self._config.lab_start_command,
            env=env,
            env_from=[V1EnvFromSource(config_map_ref=env_source)],
            image=image.reference_with_digest,
            image_pull_policy="IfNotPresent",
            ports=[V1ContainerPort(container_port=8888, name="jupyterlab")],
            resources=resources.to_kubernetes(),
            security_context=V1SecurityContext(
                allow_privilege_escalation=False,
                capabilities=V1Capabilities(drop=["all"]),
                read_only_root_filesystem=True,
                run_as_non_root=True,
                run_as_user=user.uid,
                run_as_group=user.gid,
            ),
            volume_mounts=mounts,
            working_dir=self._build_home_directory(user.username),
        )
        return [container]

    def _recreate_groups(self, pod: V1Pod) -> list[UserGroup]:
        """Recreate user group information from a Kubernetes ``Pod``.

        The GIDs are stored as supplemental groups, but the names of the
        groups go into the templating of the :file:`/etc/group` file and
        aren't easy to extract. We therefore add a serialized version of the
        group list as a pod annotation so that we can recover it during
        reconciliation.

        Parameters
        ----------
        pod
            User lab pod.

        Returns
        -------
        list of UserGroup
            User's group information.
        """
        annotation = "nublado.lsst.io/user-groups"
        groups = json.loads(pod.metadata.annotations.get(annotation, "[]"))
        return [UserGroup.model_validate(g) for g in groups]

    def _recreate_quota(
        self, resource_quota: V1ResourceQuota | None
    ) -> ResourceQuantity | None:
        """Recreate the user's quota information from Kuberentes.

        Parameters
        ----------
        resource_quota
            Kubernetes ``ResourceQuota`` object, or `None` if there was none
            for this user.

        Returns
        -------
        ResourceQuantity or None
            Corresponding user quota object, or `None` if no resource quota
            was found in Kubernetes.
        """
        if not resource_quota:
            return None
        return ResourceQuantity(
            cpu=float(resource_quota.spec.hard["limits.cpu"]),
            memory=int(resource_quota.spec.hard["limits.memory"]),
        )

    def _recreate_size(self, resources: LabResources) -> LabSize:
        """Recreate the lab size from the resources.

        Parameters
        ----------
        resources
            Discovered lab resources from Kubernetes.

        Returns
        -------
        LabSize
            The corresponding lab size if one of the known sizes matches. If
            not, returns ``LabSize.CUSTOM``.
        """
        limits = resources.limits
        for definition in self._config.sizes:
            memory = definition.memory_bytes
            if definition.cpu == limits.cpu and memory == limits.memory:
                return definition.size
        return LabSize.CUSTOM
