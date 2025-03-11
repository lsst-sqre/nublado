"""Global configuration parsing."""

from __future__ import annotations

from datetime import timedelta
from enum import Enum
from pathlib import Path
from typing import Annotated, Literal, Self

import yaml
from kubernetes_asyncio.client import (
    V1PersistentVolumeClaimSpec,
    V1PersistentVolumeSpec,
    V1ResourceRequirements,
)
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic.alias_generators import to_camel
from pydantic_settings import BaseSettings, SettingsConfigDict
from safir.logging import LogLevel, Profile
from safir.metrics import MetricsConfiguration, metrics_configuration_factory
from safir.pydantic import HumanTimedelta

from .constants import (
    KUBERNETES_NAME_PATTERN,
    LIMIT_TO_REQUEST_RATIO,
    METADATA_PATH,
    RESERVED_ENV,
    RESERVED_PATHS,
)
from .models.domain.imagefilterpolicy import RSPImageFilterPolicy
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
    "NFSPVCVolumeSource",
    "NFSVolumeSource",
    "PVCVolumeResources",
    "PVCVolumeSource",
    "TmpSource",
    "UserHomeDirectorySchema",
    "VolumeConfig",
    "VolumeMountConfig",
]


def _reject_reserved_env(v: str) -> str:
    """Pydantic validator that rejects reserved environment variables."""
    if v in RESERVED_ENV or v.startswith("JUPYTERHUB_"):
        msg = f"Lab environment variable {v} reserved for Nublado"
        raise ValueError(msg)
    return v


def _reject_reserved_paths(v: str) -> str:
    """Pydantic validator that rejects strings matching reserved paths."""
    if v in RESERVED_PATHS:
        raise ValueError(f"Cannot mount volume over {v}")
    return v


class ContainerImage(BaseModel):
    """Docker image that may be run as a container.

    The structure of this model should follow the normal Helm chart
    conventions so that `Mend Renovate`_ can detect that this is a Docker
    image reference and create pull requests to update it automatically.
    """

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )

    repository: Annotated[
        str,
        Field(
            title="Repository",
            description="Docker repository from which to pull the image",
            examples=["docker.io/lsstit/ddsnet4u"],
        ),
    ]

    pull_policy: Annotated[
        PullPolicy,
        Field(
            title="Pull policy",
            description=(
                "Kubernetes image pull policy. Set to ``Always`` when testing"
                " images that reuse the same tag."
            ),
            examples=[PullPolicy.ALWAYS],
        ),
    ] = PullPolicy.IF_NOT_PRESENT

    tag: Annotated[
        str,
        Field(
            title="Image tag",
            description="Tag of image to use (conventionally the version)",
            examples=["1.4.2"],
        ),
    ]


class BaseVolumeSource(BaseModel):
    """Source of a volume to be mounted in the lab.

    This is a base class that must be subclassed by the different supported
    ways a volume can be provided.
    """

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )

    type: Annotated[
        str, Field(title="Type of volume to mount", examples=["nfs"])
    ]


class HostPathVolumeSource(BaseVolumeSource):
    """Path on Kubernetes node to mount in the container."""

    type: Literal["hostPath"]

    path: Annotated[
        str,
        Field(
            title="Host path",
            description="Absolute host path to mount in the container",
            examples=["/home"],
            pattern="^/.*",
        ),
    ]


class NFSVolumeSource(BaseVolumeSource):
    """NFS volume to mount in the container."""

    type: Literal["nfs"]

    server: Annotated[
        str,
        Field(
            title="NFS server",
            description="Name or IP address of the NFS server for the volume",
            examples=["10.13.105.122"],
        ),
    ]

    server_path: Annotated[
        str,
        Field(
            title="Export path",
            description="Absolute path of NFS server export of the volume",
            examples=["/share1/home"],
            pattern="^/.*",
        ),
    ]

    read_only: Annotated[
        bool,
        Field(
            title="Is read-only",
            description=(
                "Whether to mount the NFS volume read-only. If this is true,"
                " any mount of this volume will be read-only even if the mount"
                " is not marked as such."
            ),
        ),
    ] = False


class PVCVolumeResources(BaseModel):
    """Resources for a persistent volume claim."""

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )

    requests: Annotated[dict[str, str], Field(title="Resource requests")]


class PVCVolumeSource(BaseVolumeSource):
    """A PVC to create to materialize the volume to mount in the container."""

    type: Literal["persistentVolumeClaim"]

    access_modes: Annotated[list[VolumeAccessMode], Field(title="Access mode")]

    storage_class_name: Annotated[str, Field(title="Storage class")]

    resources: Annotated[
        PVCVolumeResources, Field(title="Resources for volume")
    ]

    read_only: Annotated[
        bool,
        Field(
            title="Is read-only",
            description=(
                "Whether to force all mounts of this volume to read-only"
            ),
        ),
    ] = False

    def to_kubernetes_spec(self) -> V1PersistentVolumeClaimSpec:
        """Convert to the Kubernetes representation.

        Returns
        -------
        kubernetes_asyncio.client.models.V1PersistentVolumeClaimSpec
            Corresponding persistent volume claim spec.
        """
        return V1PersistentVolumeClaimSpec(
            storage_class_name=self.storage_class_name,
            access_modes=[m.value for m in self.access_modes],
            resources=V1ResourceRequirements(requests=self.resources.requests),
        )


class NFSPVCVolumeSource(BaseVolumeSource):
    """NFS+PVC volume to mount in the container.

    This is the only within-kubernetes way to specify mount options for an
    NFS mount (if you have access to the host, /etc/nfsmount.conf
    works as well).  The default mount_options are opinionated and reflect
    reasonable NFSv4 defaults in the GKE environment.

    PVs and PVCs exist in a one-to-one mapping; hence mounting this volume
    requires a PV per PVC, even though many clients can use a single NFS
    server.  Note also that PVs are cluster-scoped, not namespace-scoped,
    which complicates resource naming.

    The presence of this type will trigger the creation of the PV in the pod
    resources.
    """

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )

    type: Literal["nfsPvc"]

    server: Annotated[
        str,
        Field(
            title="NFS server",
            description="Name or IP address of the NFS server for the volume",
            examples=["10.13.105.122"],
        ),
    ]

    server_path: Annotated[
        str,
        Field(
            title="Export path",
            description="Absolute path of NFS server export of the volume",
            examples=["/share1/home"],
            pattern="^/.*",
        ),
    ]

    read_only: Annotated[
        bool,
        Field(
            title="Is read-only",
            description=(
                "Whether to mount the NFS volume read-only. If this is true,"
                " any mount of this volume will be read-only even if the mount"
                " is not marked as such."
            ),
        ),
    ] = False

    mount_options: Annotated[
        list[str],
        Field(
            title="NFS Mount Options",
            description=(
                "Mount options for NFS.  Note that if you really "
                "wanted to, you could use this to turn it back into "
                "an NFSv3 server."
            ),
        ),
    ] = [
        "rw",
        "relatime",
        "vers=4.1",
        "rsize=1048576",
        "wsize=1048576",
        "namlen=255",
        "hard",
        "proto=tcp",
        "timeo=600",
        "retrans=2",
        "sec=sys",
        "mountproto=tcp",
        "local_lock=none",
    ]

    access_modes: Annotated[list[VolumeAccessMode], Field(title="Access mode")]

    storage_class_name: Annotated[str, Field(title="Storage class")]

    resources: Annotated[
        PVCVolumeResources, Field(title="Resources for volume")
    ]

    def to_kubernetes_spec(self) -> V1PersistentVolumeClaimSpec:
        """Convert to the Kubernetes representation.

        Returns
        -------
        kubernetes_asyncio.client.models.V1PersistentVolumeClaimSpec
            Corresponding persistent volume claim spec.
        """
        return V1PersistentVolumeClaimSpec(
            storage_class_name=self.storage_class_name,
            access_modes=[m.value for m in self.access_modes],
            resources=V1ResourceRequirements(requests=self.resources.requests),
        )

    def to_kubernetes_volume_spec(self) -> V1PersistentVolumeSpec:
        """Convert to the Kubernetes representation for the matching Volume.

        Returns
        -------
        kubernetes_asyncio.client.models.V1PersistentVolumeSpec
            Corresponding persistent volume spec.
        """
        return V1PersistentVolumeSpec(
            storage_class_name=self.storage_class_name,
            access_modes=[m.value for m in self.access_modes],
            mount_options=self.mount_options,
            capacity=V1ResourceRequirements(requests=self.resources.requests),
        )


class VolumeConfig(BaseModel):
    """A volume that may be mounted inside a container."""

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )

    name: Annotated[
        str,
        Field(
            title="Name of volume",
            description=(
                "Used as the Kubernetes volume name and therefore must be a"
                " valid Kubernetes name"
            ),
            pattern=KUBERNETES_NAME_PATTERN,
        ),
    ]

    source: Annotated[
        (
            HostPathVolumeSource
            | NFSVolumeSource
            | PVCVolumeSource
            | NFSPVCVolumeSource
        ),
        Field(title="Source of volume"),
    ]


class VolumeMountConfig(BaseModel):
    """The mount of a volume inside a container."""

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )

    container_path: Annotated[
        str,
        Field(
            title="Path inside container",
            description=(
                "Absolute path at which to mount the volume in the lab"
                " container"
            ),
            examples=["/home"],
            pattern="^/.*",
        ),
        AfterValidator(_reject_reserved_paths),
    ]

    sub_path: Annotated[
        str | None,
        Field(
            title="Sub-path of source to mount",
            description="Mount only this sub-path of the volume source",
            examples=["groups"],
        ),
    ] = None

    read_only: Annotated[
        bool,
        Field(
            title="Is read-only",
            description="Whether this mount of the volume should be read-only",
            examples=[True],
        ),
    ] = False

    volume_name: Annotated[
        str,
        Field(title="Volume name", description="Name of the volume to mount"),
    ]


class FileserverConfig(BaseModel):
    """Base configuration for user file servers.

    This base model contains only the boolean setting for whether the file
    server is enabled and a few settings with defaults that are referenced
    even if the file server is disabled (mostly to make code simpler),
    allowing code to determine whether the configuration object is actually
    `EnabledFileserverConfig`.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    enabled: Annotated[
        bool,
        Field(
            title="Whether file servers are enabled",
            description=(
                "If set to false, file servers will be disabled and the routes"
                " to create or manage file servers will return 404 errors"
            ),
        ),
    ] = False

    path_prefix: Annotated[
        str,
        Field(
            title="Path prefix for file server route",
            description="The route at which users spawn new user file servers",
        ),
    ] = "/files"


class DisabledFileserverConfig(FileserverConfig):
    """Configuration when user file servers are disabled."""

    enabled: Literal[False] = False


class EnabledFileserverConfig(FileserverConfig):
    """Configuration for enabled user file servers."""

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )

    enabled: Literal[True]

    affinity: Annotated[
        Affinity | None,
        Field(
            title="Affinity rules",
            description="Node and pod affinity rules for file server pods",
        ),
    ] = None

    application: Annotated[
        str | None,
        Field(
            title="Argo CD application",
            description="Argo CD application into which to put file servers",
        ),
    ] = None

    creation_timeout: Annotated[
        HumanTimedelta,
        Field(
            title="File server creation timeout",
            description=(
                "How long to wait for a file server to start before returning"
                " an error to the user"
            ),
        ),
    ] = timedelta(minutes=2)

    delete_timeout: Annotated[
        HumanTimedelta,
        Field(
            title="File server deletion timeout",
            description=(
                "How long to wait for a file server's Kubernetes objects to be"
                " deleted before raising an error"
            ),
        ),
    ] = timedelta(minutes=1)

    extra_annotations: Annotated[
        dict[str, str],
        Field(
            title="Extra annotations",
            description=(
                "Extra annotations to add to all user file server ``Job`` and"
                " ``Pod`` Kubernetes resources"
            ),
        ),
    ] = {}

    idle_timeout: Annotated[
        HumanTimedelta,
        Field(
            title="File server inactivity timeout",
            description=(
                "After this length of time, inactive file servers will shut"
                " down"
            ),
        ),
    ] = timedelta(hours=1)

    image: Annotated[
        ContainerImage,
        Field(
            title="File server Docker image",
            description=(
                "Docker image to run as a user file server. This must follow"
                " the same API as worblehat."
            ),
        ),
    ]

    namespace: Annotated[
        str,
        Field(
            title="Namespace for user file servers",
            description=(
                "All file servers for any user will be created in this"
                " namespace"
            ),
        ),
    ]

    node_selector: Annotated[
        dict[str, str],
        Field(
            title="File server node selector",
            description=(
                "Labels that must be present on Kubernetes nodes for any file"
                " server to be scheduled there"
            ),
            examples=[{"disktype": "ssd"}],
        ),
    ] = {}

    resources: Annotated[
        LabResources | None,
        Field(
            title="Resource requests and limits",
            description=(
                "Kubernetes resource requests and limits for user file server"
                " pods"
            ),
        ),
    ] = None

    tolerations: Annotated[
        list[Toleration],
        Field(
            title="File server pod tolerations",
            description="Kubernetes tolerations for file server pods",
        ),
    ] = []

    volume_mounts: Annotated[
        list[VolumeMountConfig],
        Field(
            title="Volume mounts",
            description=(
                "Volumes mounted in the file server and exposed via WebDAV."
                " The ``containerPath`` settings represent the path visible"
                " over the WebDAV protocol."
            ),
        ),
    ] = []


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

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )

    source: DockerSourceConfig | GARSourceConfig


class LabSizeDefinition(BaseModel):
    """Possible size of lab.

    This will be used as the resource limits in Kubernetes, meaning that using
    more than this amount of CPU will result in throttling and more than this
    amount of memory may result in the lab being killed with an out-of-memory
    error. Requests will be less than this, adjusted by
    ``LIMIT_TO_REQUEST_RATIO``.
    """

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )

    size: Annotated[
        LabSize,
        Field(
            title="Lab size",
            description="Human-readable name for this lab size",
            examples=[LabSize.SMALL, LabSize.HUGE],
        ),
    ]

    cpu: Annotated[
        float,
        Field(
            title="CPU",
            description="Number of CPU cores",
            examples=[0.5],
        ),
    ]

    memory: Annotated[
        str,
        Field(
            title="Memory",
            description="Amount of memory in bytes (SI suffixes allowed)",
            examples=["1536MiB"],
        ),
    ]

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
    """Where space for :file:`/tmp` should come from."""

    DISK = "disk"
    """Use ephemeralStorage and node-local disk for :file:`/tmp`"""

    MEMORY = "memory"
    """Use tmpfs and pod memory for :file:`/tmp`"""


class LabInitContainer(BaseModel):
    """A container to run as an init container before the user's lab."""

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )

    name: Annotated[
        str,
        Field(
            title="Name of container",
            description=(
                "Name of the init container run before the user lab starts."
                " Must be unique across all init containers."
            ),
            examples=["multus-init"],
        ),
    ]

    image: Annotated[ContainerImage, Field(title="Image to run")]

    privileged: Annotated[
        bool,
        Field(
            title="Run container privileged",
            description=(
                "Whether the init container needs to run privileged to do its"
                " job. Set to true if, for example, it has to configure"
                " networking or change ownership of files or directories."
            ),
            examples=[False],
        ),
    ] = False

    volume_mounts: Annotated[
        list[VolumeMountConfig],
        Field(
            title="Volume mounts",
            description="Volumes mounted inside this init container",
        ),
    ] = []


class LabSecret(BaseModel):
    """A secret to make available to lab containers."""

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )

    secret_name: Annotated[
        str,
        Field(
            title="Source secret name",
            description=(
                "Must name a ``Secret`` resource in the same namespace as the"
                " Nublado controller pod"
            ),
            examples=["credentials"],
        ),
    ]

    secret_key: Annotated[
        str,
        Field(
            title="Key of secret",
            description=(
                "Name of field inside the ``Secret`` named ``secretName``"
                " containing the secret. Each secret key must be unique across"
                " all secrets in the list of source secrets, since it is also"
                " used as the key for the entry in the secret created in the"
                " user's lab environment."
            ),
            examples=["butler-credentials"],
        ),
    ]

    env: Annotated[
        str | None,
        Field(
            title="Environment variable to set",
            description=(
                "If set, also inject the value of this secret into the lab"
                " environment variable of this name"
            ),
            examples=["BUTLER_CREDENTIALS"],
        ),
    ] = None

    path: Annotated[
        str | None,
        Field(
            title="Path at which to mount secret",
            description=(
                "If set, also mount the secret at this path inside the lab"
                " container"
            ),
            examples=["/opt/lsst/software/jupyterlab/butler-secret"],
        ),
    ] = None


class LabNSSFiles(BaseModel):
    """Rules for :file:`/etc/passwd` and :file:`/etc/group` inside the lab."""

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )

    base_passwd: Annotated[
        str,
        Field(
            title="Base contents of ``/etc/passwd``",
            description=(
                "These contents will be copied verbatim to ``/etc/passwd``"
                " inside the lab, and then an entry for the user will be"
                " appended"
            ),
            examples=["root:x:0:0:root:/root:/bin/bash\n"],
        ),
    ] = "root:x:0:0:root:/root:/bin/bash\n"

    base_group: Annotated[
        str,
        Field(
            title="Base contents of ``/etc/group``",
            description=(
                "These contents will be copied verbatim to ``/etc/group``"
                " inside the lab, and then entries for the user's groups will"
                " be appended"
            ),
            examples=["root:x:0\n"],
        ),
    ] = "root:x:0\n"


class LabConfig(BaseModel):
    """Configuration for spawning user labs."""

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )

    activity_interval: Annotated[
        HumanTimedelta,
        Field(
            title="Activity reporting interval",
            description=(
                "How frequently the lab should report activity to JupyterHub"
            ),
        ),
    ] = timedelta(hours=1)

    application: Annotated[
        str | None,
        Field(
            title="Argo CD application",
            description="Argo CD application into which to put lab objects",
        ),
    ] = None

    affinity: Annotated[
        Affinity | None,
        Field(
            title="Affinity rules",
            description="Node and pod affinity rules for lab pods",
        ),
    ] = None

    delete_timeout: Annotated[
        HumanTimedelta,
        Field(
            title="Timeout for lab deletion",
            description=(
                "How long to wait in total for deletion of Kubernetes"
                " resources for a user lab"
            ),
            examples=[60],
        ),
    ] = timedelta(minutes=1)

    env: Annotated[
        dict[Annotated[str, AfterValidator(_reject_reserved_env)], str],
        Field(
            title="Additional lab environment variables",
            description=(
                "Additional environment variables to set in all spawned user"
                " labs"
            ),
        ),
    ] = {}

    extra_annotations: Annotated[
        dict[str, str],
        Field(
            title="Extra annotations",
            description=(
                "These annotations will be added to the Kubernetes ``Pod``"
                " resource in addition to annotations used by Nublado itself"
                " to track metadata about the pod"
            ),
        ),
    ] = {}

    files: Annotated[
        dict[Annotated[str, AfterValidator(_reject_reserved_paths)], str],
        Field(
            title="Files to create inside the lab",
            description=(
                "The key is the path inside the lab at which to mount the"
                " file, and the value describes the contents of the file."
            ),
        ),
    ] = {}

    jupyterlab_config_dir: Annotated[
        str,
        Field(
            title="Root of Lab custom Jupyterlab configuration",
            description=(
                "Path inside the lab container where custom configuration is"
                " stored.  Things like kernel definitions, custom logger"
                " definitions, service tokens, and Lab-instance-specific"
                " secrets are stored under this path."
            ),
        ),
    ] = "/opt/lsst/software/jupyterlab"

    homedir_prefix: Annotated[
        str,
        Field(
            title="Prefix for home directory path",
            description=(
                "Portion of home directory path added before the username."
                " This is the path *inside* the container, not the path of the"
                " volume mounted in the container, so it need not reflect the"
                " structure of the home directory volume source. The primary"
                " reason to set this is to make paths inside the container"
                " match a pattern that users are familiar with outside of"
                " Nublado."
            ),
            examples=["/home", "/u"],
        ),
        AfterValidator(lambda v: v.rstrip("/")),
    ] = "/home"

    homedir_schema: Annotated[
        UserHomeDirectorySchema,
        Field(
            title="Schema for user homedir construction",
            description=(
                "Determines how the username portion of the home directory"
                " path is constructed."
            ),
        ),
    ] = UserHomeDirectorySchema.USERNAME

    homedir_suffix: Annotated[
        str,
        Field(
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
        ),
        AfterValidator(lambda v: v.strip("/")),
    ] = ""

    init_containers: Annotated[
        list[LabInitContainer],
        Field(
            title="Lab init containers",
            description=(
                "Kubernetes init containers to run before user's lab starts."
                " Use these containers to do any required setup, particularly"
                " any actions that require privileges, since init containers"
                " can be run as privileged and the lab container is always run"
                " as the user."
            ),
        ),
    ] = []

    lab_start_command: Annotated[
        list[str],
        Field(
            title="Lab command",
            description=(
                "Command, as a list of strings, to run in the container to"
                " start the lab"
            ),
        ),
    ] = ["/opt/lsst/software/jupyterlab/runlab.sh"]

    namespace_prefix: Annotated[
        str,
        Field(
            title="Namespace prefix for lab environments",
            description=(
                "The name of the namespace for a user's lab will be this"
                " string, a hyphen (``-``), and the user's username"
            ),
        ),
    ]

    node_selector: Annotated[
        dict[str, str],
        Field(
            title="Lab pod node selector",
            description=(
                "Labels that must be present on Kubernetes nodes for any lab"
                " pod to be scheduled there"
            ),
            examples=[{"disktype": "ssd"}],
        ),
    ] = {}

    nss: Annotated[
        LabNSSFiles,
        Field(
            title="passwd and group contents for lab",
            description=(
                "Configuration for the ``/etc/passwd`` and ``/etc/group``"
                " files inside the lab"
            ),
        ),
    ] = LabNSSFiles()

    pull_secret: Annotated[
        str | None,
        Field(
            title="Pull secret to use for lab pods",
            description=(
                "If set, must be the name of a secret in the same namespace as"
                " the lab controller. This secret is copied to the user's lab"
                " namespace and referenced as a pull secret in the pod object."
            ),
        ),
    ] = None

    runtime_mounts_dir: Annotated[
        str,
        Field(
            title="Runtime-info mounts",
            description=(
                "Directory under which runtime information (e.g. tokens,"
                " environment variables, and container resource information"
                " will be mounted."
            ),
        ),
    ] = "/opt/lsst/software/jupyterlab"

    secrets: Annotated[
        list[LabSecret],
        Field(
            title="Lab secrets",
            description="Secrets to make available inside lab",
        ),
    ] = []

    sizes: Annotated[
        list[LabSizeDefinition],
        Field(
            title="Possible lab sizes",
            description=(
                "Only these sizes will be present in the menu, in the order in"
                " which they're defined in the configuration file. The first"
                " size defined will be the default."
            ),
        ),
    ] = []

    spawn_timeout: Annotated[
        HumanTimedelta,
        Field(
            title="Timeout for lab spawning",
            description=(
                "Creation of the lab will fail if it takes longer than this"
                " for the lab pod to be created and start running. This does"
                " not include the time spent by JupyterHub waiting for the lab"
                " to start listening to the network. It should generally be"
                " shorter than the spawn timeout set in JupyterHub."
            ),
            examples=[300],
        ),
    ] = timedelta(minutes=10)

    tmp_source: Annotated[
        TmpSource,
        Field(
            title="Source (memory or disk) for lab :file:`/tmp`",
            description=(
                "Select whether the pod's :file:`/tmp` will come from memory"
                " or node-local disk. Both are scarce resources, and the"
                " appropriate choice is environment-dependent."
            ),
        ),
    ] = TmpSource.MEMORY

    tolerations: Annotated[
        list[Toleration],
        Field(
            title="File server pod tolerations",
            description="Kubernetes tolerations for file server pods",
        ),
    ] = []

    volumes: Annotated[
        list[VolumeConfig],
        Field(
            title="Available volumes",
            description=(
                "Volumes available to mount inside either the lab container or"
                " an init container. Inclusion in this list does not mean that"
                " they will be mounted. They must separately be listed under"
                " ``volumeMounts`` for either an init container or the main"
                " lab configuration."
            ),
        ),
    ] = []

    volume_mounts: Annotated[
        list[VolumeMountConfig],
        Field(
            title="Mounted volumes",
            description="Volumes to mount inside the lab container",
        ),
    ] = []

    @field_validator("homedir_prefix")
    @classmethod
    def _validate_homedir_prefix(cls, v: str) -> str:
        if not v.startswith("/") or len(v) < 2:
            raise ValueError("Invalid home directory prefix")
        return v

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

    model_config = SettingsConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )

    base_url: Annotated[
        str,
        Field(
            title="Base URL for Science Platform",
            description="Injected into the lab pod as EXTERNAL_INSTANCE_URL",
            validation_alias="EXTERNAL_INSTANCE_URL",
        ),
    ] = "http://127.0.0.1:8080"

    log_level: Annotated[
        LogLevel,
        Field(
            title="Log level",
            description="Python logging level",
            examples=[LogLevel.INFO],
        ),
    ] = LogLevel.INFO

    metadata_path: Annotated[
        Path,
        Field(
            title="Path to injected pod metadata",
            description=(
                "This directory should contain files named ``name``,"
                " ``namespace``, and ``uid``, which should contain the name,"
                " namespace, and UUID of the lab controller pod, respectively."
                " Normally this is done via the Kubernetes ``downwardAPI``.)"
                " These are used to set ownership information on pods spawned"
                " by the prepuller and to find secrets to inject into the lab."
            ),
        ),
    ] = METADATA_PATH

    metrics: MetricsConfiguration = Field(
        default_factory=metrics_configuration_factory,
        title="Metrics configuration",
        description="Configuration for reporting metrics to Kafka",
    )

    name: Annotated[
        str,
        Field(
            title="Name of application",
            description="Used when reporting problems to Slack",
        ),
    ] = "Nublado"

    path_prefix: Annotated[
        str,
        Field(
            title="URL prefix for controller API",
            description=(
                "This prefix is used for all APIs except for the API to spawn"
                " a user file server. That is controlled by"
                " ``fileserver.path_prefix``."
            ),
        ),
    ] = "/nublado"

    profile: Annotated[
        Profile,
        Field(
            title="Application logging profile",
            description=(
                "``production`` uses JSON logging. ``development`` uses"
                " logging that may be easier for humans to read but that"
                " cannot be easily parsed by computers or Google Log Explorer."
            ),
            examples=[Profile.development],
        ),
    ] = Profile.production

    slack_webhook: Annotated[
        SecretStr | None,
        Field(
            title="Slack webhook for alerts",
            description=(
                "If set, failures creating user labs or file servers and any"
                " uncaught exceptions in the Nublado controller will be"
                " reported to Slack via this webhook"
            ),
            validation_alias="NUBLADO_SLACK_WEBHOOK",
        ),
    ] = None

    fileserver: Annotated[
        DisabledFileserverConfig | EnabledFileserverConfig,
        Field(title="User file server configuration"),
    ] = DisabledFileserverConfig()

    images: Annotated[
        PrepullerConfig,
        Field(
            title="Available lab images",
            description=(
                "Configuration for which images to prepull and to"
                " display in the spawner menu for users to choose from when"
                " spawning labs"
            ),
        ),
    ]

    dropdown_menu: Annotated[
        RSPImageFilterPolicy,
        Field(
            title="Dropdown menu display policy",
            description=(
                "Configuration for which images are displayed in the"
                " spawner dropdown menu for users to choose from when"
                " spawning labs."
            ),
            default_factory=RSPImageFilterPolicy,
        ),
    ]

    lab: Annotated[LabConfig, Field(title="User lab configuration")]

    @model_validator(mode="after")
    def _validate_fileserver_volume_mounts(self) -> Self:
        if not isinstance(self.fileserver, EnabledFileserverConfig):
            return self
        volumes = {v.name for v in self.lab.volumes}
        for mount in self.fileserver.volume_mounts:
            if mount.volume_name not in volumes:
                name = mount.volume_name
                msg = f"Unknown mounted volume {name} in file servers"
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
