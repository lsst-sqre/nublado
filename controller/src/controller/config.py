"""Global configuration parsing."""

from __future__ import annotations

from datetime import timedelta
from enum import Enum
from pathlib import Path
from typing import Literal, Self

import yaml
from kubernetes_asyncio.client import (
    V1PersistentVolumeClaimSpec,
    V1ResourceRequirements,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from pydantic.alias_generators import to_camel
from pydantic_settings import BaseSettings, SettingsConfigDict
from safir.logging import LogLevel, Profile
from safir.pydantic import HumanTimedelta

from .constants import (
    KUBERNETES_NAME_PATTERN,
    LIMIT_TO_REQUEST_RATIO,
    METADATA_PATH,
    RESERVED_ENV,
    RESERVED_PATHS,
)
from .models.domain.kubernetes import (
    Affinity,
    PullPolicy,
    Toleration,
    VolumeAccessMode,
)
from .models.v1.lab import LabResources, LabSize, ResourceQuantity
from .models.v1.prepuller import (
    DockerSourceOptions,
    GARSourceOptions,
    PrepullerOptions,
)
from .units import memory_to_bytes

__all__ = [
    "BaseVolumeSource",
    "Config",
    "ContainerImage",
    "DisabledFileserverConfig",
    "EnabledFileserverConfig",
    "FileserverConfig",
    "HostPathVolumeSource",
    "LabConfig",
    "LabInitContainer",
    "LabNSSFiles",
    "LabSecret",
    "LabSizeDefinition",
    "NFSVolumeSource",
    "PVCVolumeResources",
    "PVCVolumeSource",
    "TmpSource",
    "UserHomeDirectorySchema",
    "VolumeConfig",
    "VolumeMountConfig",
]


class ContainerImage(BaseModel):
    """Docker image that may be run as a container.

    The structure of this model should follow the normal Helm chart
    conventions so that `Mend Renovate`_ can detect that this is a Docker
    image reference and create pull requests to update it automatically.
    """

    repository: str = Field(
        ...,
        title="Repository",
        description="Docker repository from which to pull the image",
        examples=["docker.io/lsstit/ddsnet4u"],
    )

    pull_policy: PullPolicy = Field(
        PullPolicy.IF_NOT_PRESENT,
        title="Pull policy",
        description=(
            "Kubernetes image pull policy. Set to ``Always`` when testing"
            " images that reuse the same tag."
        ),
        examples=[PullPolicy.ALWAYS],
    )

    tag: str = Field(
        ...,
        title="Image tag",
        description="Tag of image to use (conventionally the version)",
        examples=["1.4.2"],
    )

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )


class BaseVolumeSource(BaseModel):
    """Source of a volume to be mounted in the lab.

    This is a base class that must be subclassed by the different supported
    ways a volume can be provided.
    """

    type: str = Field(..., title="Type of volume to mount", examples=["nfs"])

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )


class HostPathVolumeSource(BaseVolumeSource):
    """Path on Kubernetes node to mount in the container."""

    type: Literal["hostPath"] = Field(..., title="Type of volume to mount")

    path: str = Field(
        ...,
        title="Host path",
        description="Absolute host path to mount in the container",
        examples=["/home"],
        pattern="^/.*",
    )


class NFSVolumeSource(BaseVolumeSource):
    """NFS volume to mount in the container."""

    type: Literal["nfs"] = Field(..., title="Type of volume to mount")

    server: str = Field(
        ...,
        title="NFS server",
        description="Name or IP address of the server providing the volume",
        examples=["10.13.105.122"],
    )

    server_path: str = Field(
        ...,
        title="Export path",
        description="Absolute path of NFS server export of the volume",
        examples=["/share1/home"],
        pattern="^/.*",
    )

    read_only: bool = Field(
        False,
        title="Is read-only",
        description=(
            "Whether to mount the NFS volume read-only. If this is true,"
            " any mount of this volume will be read-only even if the mount"
            " is not marked as such."
        ),
    )


class PVCVolumeResources(BaseModel):
    """Resources for a persistent volume claim."""

    requests: dict[str, str] = Field(..., title="Resource requests")

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )


class PVCVolumeSource(BaseVolumeSource):
    """A PVC to create to materialize the volume to mount in the container."""

    type: Literal["persistentVolumeClaim"] = Field(
        ..., title="Type of volume to mount"
    )

    access_modes: list[VolumeAccessMode] = Field(..., title="Access mode")

    storage_class_name: str = Field(..., title="Storage class")

    resources: PVCVolumeResources = Field(..., title="Resources for volume")

    read_only: bool = Field(
        False,
        title="Is read-only",
        description=(
            "If set to true, forces all mounts of this volume to read-only"
        ),
    )

    def to_kubernetes_spec(self) -> V1PersistentVolumeClaimSpec:
        """Convert to the Kubernetes representation.

        Returns
        -------
        kubernetes_asyncio.client.models.V1PersistentVolumeClaimSpec
            Corresponding persistente volume claim spec.
        """
        return V1PersistentVolumeClaimSpec(
            storage_class_name=self.storage_class_name,
            access_modes=[m.value for m in self.access_modes],
            resources=V1ResourceRequirements(requests=self.resources.requests),
        )


class VolumeConfig(BaseModel):
    """A volume that may be mounted inside a container."""

    name: str = Field(
        ...,
        title="Name of volume",
        description=(
            "Used as the Kubernetes volume name and therefore must be a"
            " valid Kubernetes name"
        ),
        pattern=KUBERNETES_NAME_PATTERN,
    )

    source: HostPathVolumeSource | NFSVolumeSource | PVCVolumeSource = Field(
        ..., title="Source of volume"
    )

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )


class VolumeMountConfig(BaseModel):
    """The mount of a volume inside a container."""

    container_path: str = Field(
        ...,
        title="Path inside container",
        description=(
            "Absolute path at which to mount the volume in the lab container"
        ),
        examples=["/home"],
        pattern="^/.*",
    )

    sub_path: str | None = Field(
        None,
        title="Sub-path of source to mount",
        description="Mount only this sub-path of the volume source",
        examples=["groups"],
    )

    read_only: bool = Field(
        False,
        title="Is read-only",
        description=(
            "Whether the volume should be mounted read-only in the container"
        ),
        examples=[True],
    )

    volume_name: str = Field(
        ..., title="Volume name", description="Name of the volume to mount"
    )

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )

    @field_validator("container_path")
    @classmethod
    def _validate_container_path(cls, v: str) -> str:
        if v in RESERVED_PATHS:
            raise ValueError(f"Cannot mount volume over {v}")
        return v


class FileserverConfig(BaseModel):
    """Base configuration for user file servers.

    This base model contains only the boolean setting for whether the file
    server is enabled and a few settings with defaults that are referenced
    even if the file server is disabled (mostly to make code simpler),
    allowing code to determine whether the configuration object is actually
    `EnabledFileserverConfig`.
    """

    enabled: bool = Field(
        False,
        title="Whether file servers are enabled",
        description=(
            "If set to false, file servers will be disabled and the routes"
            " to create or manage file servers will return 404 errors"
        ),
    )

    path_prefix: str = Field(
        "/files",
        title="Path prefix for file server route",
        description="The route at which users spawn new user file servers",
    )

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class DisabledFileserverConfig(FileserverConfig):
    """Configuration when user file servers are disabled."""

    enabled: Literal[False] = False


class EnabledFileserverConfig(FileserverConfig):
    """Configuration for enabled user file servers."""

    enabled: Literal[True]

    affinity: Affinity | None = Field(
        None,
        title="Affinity rules",
        description="Node and pod affinity rules for file server pods",
    )

    application: str | None = Field(
        None,
        title="Argo CD application",
        description=(
            "An Argo CD application under which fileservers should be shown"
        ),
    )

    creation_timeout: HumanTimedelta = Field(
        timedelta(minutes=2),
        title="File server creation timeout",
        description=(
            "How long to wait for a file server to start before returning an"
            " error to the user"
        ),
    )

    delete_timeout: HumanTimedelta = Field(
        timedelta(minutes=1),
        title="File server deletion timeout",
        description=(
            "How long to wait for a file server's Kubernetes objects to be"
            " deleted before raising an error"
        ),
    )

    extra_annotations: dict[str, str] = Field(
        {},
        title="Extra annotations",
        description=(
            "Extra annotations to add to all user file server ``Job`` and"
            " ``Pod`` Kubernetes resources"
        ),
    )

    idle_timeout: HumanTimedelta = Field(
        timedelta(hours=1),
        title="File server inactivity timeout",
        description=(
            "After this length of time, inactive file servers will shut down"
        ),
    )

    image: ContainerImage = Field(
        ...,
        title="File server Docker image",
        description=(
            "Docker image to run as a user file server. This must follow the"
            " same API as worblehat."
        ),
    )

    namespace: str = Field(
        ...,
        title="Namespace for user file servers",
        description=(
            "All file servers for any user will be created in this namespace"
        ),
    )

    node_selector: dict[str, str] = Field(
        {},
        title="File server node selector",
        description=(
            "Labels that must be present on Kubernetes nodes for any file"
            " server to be scheduled there"
        ),
        examples=[{"disktype": "ssd"}],
    )

    resources: LabResources | None = Field(
        None,
        title="Resource requests and limits",
        description=(
            "Kubernetes resource requests and limits for user file server"
            " pods"
        ),
    )

    tolerations: list[Toleration] = Field(
        [],
        title="File server pod tolerations",
        description="Kubernetes tolerations for file server pods",
    )

    volume_mounts: list[VolumeMountConfig] = Field(
        [],
        title="Volume mounts",
        description=(
            "Volumes mounted in the file server and exposed via WebDAV."
            " The ``containerPath`` settings represent the path visible over"
            " the WebDAV protocol."
        ),
    )

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )


class DockerSourceConfig(DockerSourceOptions):
    """Configuration for a Docker source.

    This is identical to the API model used to return the prepuller
    configuration to an API client except that camel-case aliases are enabled.
    """

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )


class GARSourceConfig(GARSourceOptions):
    """Configuration for a Google Artifact Registry source.

    This is identical to the API model used to return the prepuller
    configuration to an API client except that camel-case aliases are enabled.
    """

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )


class PrepullerConfig(PrepullerOptions):
    """Configuration for the prepuller.

    This is identical to the API model used to return the prepuller
    configuration to an API client except that camel-case aliases are enabled.
    """

    source: DockerSourceConfig | GARSourceConfig

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )


class LabSizeDefinition(BaseModel):
    """Possible size of lab.

    This will be used as the resource limits in Kubernetes, meaning that using
    more than this amount of CPU will result in throttling and more than this
    amount of memory may result in the lab being killed with an out-of-memory
    error. Requests will be less than this, adjusted by
    ``LIMIT_TO_REQUEST_RATIO``.
    """

    size: LabSize = Field(
        ...,
        title="Lab size",
        description="Human-readable name for this lab size",
        examples=[LabSize.SMALL, LabSize.HUGE],
    )

    cpu: float = Field(
        ...,
        title="CPU",
        description="Number of CPU cores",
        examples=[0.5],
    )

    memory: str = Field(
        ...,
        title="Memory",
        description="Amount of memory in bytes (SI suffixes allowed)",
        examples=["1536MiB"],
    )

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )

    def __str__(self) -> str:
        return f"{self.size.value.title()} ({self.cpu} CPU, {self.memory} RAM)"

    @property
    def memory_bytes(self) -> int:
        """Amount of memory in bytes."""
        return memory_to_bytes(self.memory)

    def to_lab_resources(self) -> LabResources:
        """Convert to the equivalent lab resources model."""
        return LabResources(
            limits=ResourceQuantity(cpu=self.cpu, memory=self.memory_bytes),
            requests=ResourceQuantity(
                cpu=self.cpu / LIMIT_TO_REQUEST_RATIO,
                memory=int(self.memory_bytes / LIMIT_TO_REQUEST_RATIO),
            ),
        )


class UserHomeDirectorySchema(Enum):
    """Algorithm for building a user's home directory path."""

    USERNAME = "username"
    """Paths like ``/home/rachel``."""

    INITIAL_THEN_USERNAME = "initialThenUsername"
    """Paths like ``/home/r/rachel``."""


class TmpSource(Enum):
    """Whether :file:`/tmp` should come from disk (and thus ephemeralStorage)
    or memory-as-tmpfs (and thus pod memory).
    """

    DISK = "disk"
    """Use ephemeralStorage and node-local disk for :file:`/tmp`"""

    MEMORY = "memory"
    """Use tmpfs and pod memory for :file:`/tmp`"""


class LabInitContainer(BaseModel):
    """A container to run as an init container before the user's lab."""

    name: str = Field(
        ...,
        title="Name of container",
        description=(
            "Name of the init container run before the user lab starts. Must"
            " be unique across all init containers."
        ),
        examples=["multus-init"],
    )

    image: ContainerImage = Field(..., title="Image to run")

    privileged: bool = Field(
        False,
        title="Run container privileged",
        description=(
            "Whether the init container needs to run privileged to do its job."
            " Set to true if, for example, it has to configure networking or"
            " change ownership of files or directories."
        ),
        examples=[False],
    )

    volume_mounts: list[VolumeMountConfig] = Field(
        [],
        title="Volume mounts",
        description="Volumes mounted inside this init container",
    )

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )


class LabSecret(BaseModel):
    """A secret to make available to lab containers."""

    secret_name: str = Field(
        ...,
        title="Source secret name",
        description=(
            "Must name a ``Secret`` resource in the same namespace as the"
            " Nublado controller pod"
        ),
        examples=["credentials"],
    )

    secret_key: str = Field(
        ...,
        title="Key of secret",
        description=(
            "Name of field inside the ``Secret`` named ``secretName``"
            " containing the secret. Each secret key must be unique across all"
            " secrets in the list of source secrets, since it is also used as"
            " the key for the entry in the secret created in the user's lab"
            " environment."
        ),
        examples=["butler-credentials"],
    )

    env: str | None = Field(
        None,
        title="Environment variable to set",
        description=(
            "If set, also inject the value of this secret into the lab"
            " environment variable of this name"
        ),
        examples=["BUTLER_CREDENTIALS"],
    )

    path: str | None = Field(
        None,
        title="Path at which to mount secret",
        description=(
            "If set, also mount the secret at this path inside the lab"
            " container"
        ),
        examples=["/opt/lsst/software/jupyterlab/butler-secret"],
    )

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )


class LabNSSFiles(BaseModel):
    """Rules for :file:`/etc/passwd` and :file:`/etc/group` inside the lab."""

    base_passwd: str = Field(
        "root:x:0:0:root:/root:/bin/bash\n",
        title="Base contents of ``/etc/passwd``",
        description=(
            "These contents will be copied verbatim to ``/etc/passwd`` inside"
            " the lab, and then an entry for the user will be appended"
        ),
        examples=["root:x:0:0:root:/root:/bin/bash\n"],
    )

    base_group: str = Field(
        "root:x:0\n",
        title="Base contents of ``/etc/group``",
        description=(
            "These contents will be copied verbatim to ``/etc/group`` inside"
            " the lab, and then entries for the user's groups will be"
            " appended"
        ),
        examples=["root:x:0\n"],
    )

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )


class LabConfig(BaseModel):
    """Configuration for spawning user labs."""

    application: str | None = Field(
        None,
        title="Argo CD application",
        description=(
            "An Argo CD application under which lab objects should be shown"
        ),
    )

    affinity: Affinity | None = Field(
        None,
        title="Affinity rules",
        description="Node and pod affinity rules for lab pods",
    )

    delete_timeout: HumanTimedelta = Field(
        timedelta(minutes=1),
        title="Timeout for lab deletion",
        description=(
            "How long to wait in total for deletion of Kubernetes resources"
            " for a user lab"
        ),
        examples=[60],
    )

    env: dict[str, str] = Field(
        {},
        title="Additional lab environment variables",
        description=(
            "Additional environment variables to set in all spawned user labs"
        ),
    )

    extra_annotations: dict[str, str] = Field(
        {},
        title="Extra annotations",
        description=(
            "These annotations will be added to the Kubernetes ``Pod``"
            " resource in addition to annotations used by Nublado itself to"
            " track metadata about the pod"
        ),
    )

    files: dict[str, str] = Field(
        {},
        title="Files to create inside the lab",
        description=(
            "The key is the path inside the lab at which to mount the file,"
            " and the value describes the contents of the file."
        ),
    )

    jupyterlab_config_dir: str = Field(
        "/opt/lsst/software/jupyterlab",
        title="Root of Lab custom Jupyterlab configuration",
        description=(
            "Path inside the lab container where custom configuration is"
            " stored.  Things like kernel definitions, custom logger"
            " definitions, service tokens, and Lab-instance-specific secrets"
            " are stored under this path."
        ),
    )

    homedir_prefix: str = Field(
        "/home",
        title="Prefix for home directory path",
        description=(
            "Portion of home directory path added before the username. This"
            " is the path *inside* the container, not the path of the volume"
            " mounted in the container, so it need not reflect the structure"
            " of the home directory volume source. The primary reason to set"
            " this is to make paths inside the container match a pattern that"
            " users are familiar with outside of Nublado."
        ),
        examples=["/home", "/u"],
    )

    homedir_schema: UserHomeDirectorySchema = Field(
        UserHomeDirectorySchema.USERNAME,
        title="Schema for user homedir construction",
        description=(
            "Determines how the username portion of the home directory path"
            " is constructed."
        ),
    )

    homedir_suffix: str = Field(
        "",
        title="Suffix for home directory path",
        description=(
            "Portion of home directory path added after the username. This"
            " is primarily used for environments that want the user's"
            " Nublado home directory to be a subdirectory of their regular"
            " home directory outside of Nublado. This configuration is"
            " strongly recommended in environments that change home"
            " directories, since Nublado often has different needs for"
            " dot files and other configuration."
        ),
        examples=["nublado", "jhome"],
    )

    init_containers: list[LabInitContainer] = Field(
        [],
        title="Lab init containers",
        description=(
            "Kubernetes init containers to run before user's lab starts. Use"
            " these containers to do any required setup, particularly any"
            " actions that require privileges, since init containers can be"
            " run as privileged and the lab container is always run as the"
            " user."
        ),
    )

    lab_start_command: list[str] = Field(
        ["/opt/lsst/software/jupyterlab/runlab.sh"],
        title="Lab command",
        description=(
            "This is the executable in the container that will be run to"
            " start the lab, and its arguments, supplied as a list of strings."
        ),
    )

    namespace_prefix: str = Field(
        ...,
        title="Namespace prefix for lab environments",
        description=(
            "The namespace for the user's lab will start with this string,"
            " a hyphen (``-``), and the user's username"
        ),
    )

    node_selector: dict[str, str] = Field(
        {},
        title="Lab pod node selector",
        description=(
            "Labels that must be present on Kubernetes nodes for any lab pod"
            " to be scheduled there"
        ),
        examples=[{"disktype": "ssd"}],
    )

    nss: LabNSSFiles = Field(
        default_factory=LabNSSFiles,
        title="passwd and group contents for lab",
        description=(
            "Configuration for the ``/etc/passwd`` and ``/etc/group`` files"
            " inside the lab"
        ),
    )

    pull_secret: str | None = Field(
        None,
        title="Pull secret to use for lab pods",
        description=(
            "If set, must be the name of a secret in the same namespace as"
            " the lab controller. This secret is copied to the user's lab"
            " namespace and referenced as a pull secret in the pod object."
        ),
    )

    runtime_mounts_dir: str = Field(
        "/opt/lsst/software/jupyterlab",
        title="Runtime-info mounts",
        description=(
            "Directory under which runtime information (e.g. tokens,"
            " environment variables, and container resource information"
            " will be mounted."
        ),
    )

    secrets: list[LabSecret] = Field(
        [],
        title="Lab secrets",
        description="Secrets to make available inside lab",
    )

    sizes: list[LabSizeDefinition] = Field(
        [],
        title="Possible lab sizes",
        description=(
            "Only these sizes will be present in the menu, in the order in"
            " which they're defined in the configuration file. The first"
            " size defined will be the default."
        ),
    )

    spawn_timeout: HumanTimedelta = Field(
        timedelta(minutes=10),
        title="Timeout for lab spawning",
        description=(
            "Creation of the lab will fail if it takes longer than this for"
            " the lab pod to be created and start running. This does not"
            " include the time spent by JupyterHub waiting for the lab to"
            " start listening to the network. It should generally be shorter"
            " than the spawn timeout set in JupyterHub."
        ),
        examples=[300],
    )

    tmp_source: TmpSource = Field(
        TmpSource.MEMORY,
        title="Source (memory or disk) for lab :file:`/tmp`",
        description=(
            "Use this to select whether the pod's :file:`/tmp` will come from"
            " memory or node-local disk.  Both are scarce resources, and"
            " the appropriate choice is environment-dependent."
        ),
    )

    tolerations: list[Toleration] = Field(
        [],
        title="File server pod tolerations",
        description="Kubernetes tolerations for file server pods",
    )

    volumes: list[VolumeConfig] = Field(
        [],
        title="Available volumes",
        description=(
            "Volumes available to mount inside either the lab container or"
            " an init container. Inclusion in this list does not mean that"
            " they will be mounted. They must separately be listed under"
            " ``volumeMounts`` for either an init container or the main lab"
            " configuration."
        ),
    )

    volume_mounts: list[VolumeMountConfig] = Field(
        [],
        title="Mounted volumes",
        description="Volumes to mount inside the lab container",
    )

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )

    @field_validator("env")
    @classmethod
    def _validate_env(cls, v: dict[str, str]) -> dict[str, str]:
        for key in v:
            if key in RESERVED_ENV:
                msg = (
                    f"Lab environment variable {key} reserved for the Nublado"
                    " controller or JupyterHub"
                )
                raise ValueError(msg)
            if key.startswith("JUPYTERHUB_"):
                msg = (
                    "Environment variables starting with JUPYTERHUB_ reserved"
                    " for JupyterHub"
                )
                raise ValueError(msg)
        return v

    @field_validator("files")
    @classmethod
    def _validate_files(cls, v: dict[str, str]) -> dict[str, str]:
        for path in v:
            if path in RESERVED_PATHS:
                raise ValueError(f"Cannot mount a file over {path}")
        return v

    @field_validator("homedir_prefix")
    @classmethod
    def _validate_homedir_prefix(cls, v: str) -> str:
        v = v.rstrip("/")
        if not v.startswith("/") or len(v) < 2:
            raise ValueError("Invalid home directory prefix")
        return v

    @field_validator("homedir_suffix")
    @classmethod
    def _validate_homedir_suffix(cls, v: str) -> str:
        return v.strip("/")

    @field_validator("secrets")
    @classmethod
    def _validate_secrets(cls, v: list[LabSecret]) -> list[LabSecret]:
        keys = set()
        for secret in v:
            if secret.secret_key == "token":
                msg = 'secret_key "token" is reserved and may not be used'
                raise ValueError(msg)
            if secret.secret_key in keys:
                msg = f"Duplicate secret_key {secret.secret_key}"
                raise ValueError(msg)
            keys.add(secret.secret_key)
        return v

    @field_validator("sizes")
    @classmethod
    def _validate_sizes(
        cls, v: list[LabSizeDefinition]
    ) -> list[LabSizeDefinition]:
        if not v:
            raise ValueError("At least one lab size must be defined")
        seen = set()
        for definition in v:
            if definition.size in seen:
                raise ValueError(f"Duplicate lab size {definition.size.value}")
            seen.add(definition.size)
        return v

    @model_validator(mode="after")
    def _validate_volumes(self) -> Self:
        volumes = {v.name for v in self.volumes}
        for mount in self.volume_mounts:
            if mount.volume_name not in volumes:
                raise ValueError(f"Unknown mounted volume {mount.volume_name}")
        for container in self.init_containers:
            for mount in container.volume_mounts:
                if mount.volume_name not in volumes:
                    msg = f"Unknown mounted volume {mount.volume_name}"
                    raise ValueError(msg)
        return self

    def get_size_definition(self, size: LabSize) -> LabSizeDefinition:
        """Return the definition for a given lab size.

        Parameters
        ----------
        size
            Size of lab.

        Returns
        -------
        LabSizeDefinition
            Corresponding definition.

        Raises
        ------
        KeyError
            Raised if that lab size is not defined.
        """
        for definition in self.sizes:
            if definition.size == size:
                return definition
        raise KeyError(f"Lab size {size.value} not defined")


class Config(BaseSettings):
    """Nublado controller configuration."""

    base_url: str = Field(
        "http://127.0.0.1:8080",
        title="Base URL for Science Platform",
        description="Injected into the lab pod as EXTERNAL_INSTANCE_URL",
        validation_alias="EXTERNAL_INSTANCE_URL",
    )

    log_level: LogLevel = Field(
        LogLevel.INFO,
        title="Log level",
        description="Python logging level",
        examples=[LogLevel.INFO],
    )

    metadata_path: Path = Field(
        METADATA_PATH,
        title="Path to injected pod metadata",
        description=(
            "This directory should contain files named ``name``,"
            " ``namespace``, and ``uid``, which should contain the name,"
            " namespace, and UUID of the lab controller pod, respectively."
            " Normally this is done via the Kubernetes ``downwardAPI``.)"
            " These are used to set ownership information on pods spawned by"
            " the prepuller and to find secrets to inject into the lab."
        ),
    )

    name: str = Field(
        "Nublado",
        title="Name of application",
        description="Used when reporting problems to Slack",
    )

    path_prefix: str = Field(
        "/nublado",
        title="URL prefix for controller API",
        description=(
            "This prefix is used for all APIs except for the API to spawn a"
            " user file server. That is controlled by"
            " ``fileserver.path_prefix``."
        ),
    )

    profile: Profile = Field(
        Profile.production,
        title="Application logging profile",
        description=(
            "``production`` uses JSON logging. ``development`` uses logging"
            " that may be easier for humans to read but that cannot be easily"
            " parsed by computers or Google Log Explorer."
        ),
        examples=[Profile.development],
    )

    slack_webhook: str | None = Field(
        None,
        title="Slack webhook for alerts",
        description=(
            "If set, failures creating user labs or file servers and any"
            " uncaught exceptions in the Nublado controller will be reported"
            " to Slack via this webhook"
        ),
        validation_alias="NUBLADO_SLACK_WEBHOOK",
    )

    fileserver: DisabledFileserverConfig | EnabledFileserverConfig = Field(
        DisabledFileserverConfig(), title="User file server configuration"
    )

    images: PrepullerConfig = Field(
        ...,
        title="Available lab images",
        description=(
            "Configuration for which images to prepull and which images to"
            " display in the spawner menu for users to choose from when"
            " spawning labs"
        ),
    )

    lab: LabConfig = Field(..., title="User lab configuration")

    model_config = SettingsConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )

    @model_validator(mode="after")
    def _validate_fileserver_volume_mounts(self) -> Self:
        if not isinstance(self.fileserver, EnabledFileserverConfig):
            return self
        volumes = {v.name for v in self.lab.volumes}
        for mount in self.fileserver.volume_mounts:
            if mount.volume_name not in volumes:
                msg = (
                    f"Unknown mounted volume {mount.volume_name} in file"
                    " servers"
                )
                raise ValueError(msg)
        return self

    @classmethod
    def from_file(cls, path: Path) -> Self:
        """Load the controller configuration from a YAML file.

        Parameters
        ----------
        path
            Path to the configuration file.
        """
        with path.open("r") as f:
            return cls.model_validate(yaml.safe_load(f))
