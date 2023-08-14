"""Global configuration parsing."""

from __future__ import annotations

import os
from datetime import timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Optional, Self

import yaml
from pydantic import BaseSettings, Field, root_validator, validator
from safir.logging import LogLevel, Profile
from safir.pydantic import CamelCaseModel, to_camel_case

from .constants import DOCKER_SECRETS_PATH, METADATA_PATH
from .models.v1.lab import LabResources, LabSize
from .models.v1.prepuller_config import PrepullerConfig


def _get_namespace_prefix() -> str:
    """Determine the prefix to use for namespaces for lab environments.

    Use the namespace of the running pod as the prefix if we can determine
    what it is, otherwise falls back on ``userlabs``.

    Returns
    -------
    str
        Namespace prefix to use for namespaces for lab environments.
    """
    if prefix := os.getenv("USER_NAMESPACE_PREFIX"):
        return prefix

    # Kubernetes puts the running pod namespace here.
    path = Path("/var/run/secrets/kubernetes.io/serviceaccount/namespace")
    if path.exists():
        return path.read_text().strip()
    else:
        return "userlabs"


#
# Safir
#


class SafirConfig(CamelCaseModel):
    """Config common to most Safir-based applications."""

    name: str = Field(
        "Nublado",
        title="Name of application",
        env="SAFIR_NAME",
    )

    path_prefix: str = Field(
        "/nublado",
        title="URL prefix for application API",
        env="SAFIR_PATH_PREFIX",
    )

    profile: Profile = Field(
        Profile.production,
        title="Application logging profile",
        env="SAFIR_PROFILE",
    )

    log_level: LogLevel = Field(
        LogLevel.INFO,
        example=LogLevel.INFO,
        title="Application log level",
    )


#
# Lab
#


class LabSizeDefinition(CamelCaseModel):
    cpu: float = Field(
        ...,
        title="Number of CPU resource units for container",
        example=0.5,
        description=(
            "See https://kubernetes.io/docs/concepts/configuration/"
            "manage-resources-containers/"
        ),
    )
    memory: str = Field(
        ...,
        title="Amount of memory for Lab container.",
        example="1536MiB",
        description="Must be specified as a text string (e.g. '1536MiB')",
    )


class UserHomeDirectorySchema(Enum):
    """Possible ways a homedir may be constructed."""

    USERNAME = "username"  # /home/rachel
    INITIAL_THEN_USERNAME = "initialThenUsername"  # /home/r/rachel


class FileMode(Enum):
    """Possible read/write modes with which a file may be mounted."""

    RW = "rw"
    RO = "ro"


class BaseVolumeSource(CamelCaseModel):
    """Source of a volume to be mounted in the lab.

    This is a base class that must be subclassed by the different supported
    ways a volume can be provided.
    """

    type: str = Field(..., title="Type of volume to mount", example="nfs")


class HostPathVolumeSource(BaseVolumeSource):
    """A hostPath volume to be mounted in the container."""

    type: Literal["hostPath"] = Field(..., title="Type of volume to mount")
    path: str = Field(
        ...,
        title="Absolute host path to mount in the container",
        example="/home",
        regex="^/.*",
    )


class NFSVolumeSource(BaseVolumeSource):
    """An NFS volume to be mounted in the container."""

    type: Literal["nfs"] = Field(..., title="Type of volume to mount")
    server: str = Field(
        ...,
        title="Name or address of the server providing the volume",
        example="10.13.105.122",
    )
    server_path: str = Field(
        ...,
        title="Absolute path where the volume is exported from the NFS server",
        example="/share1/home",
        regex="^/.*",
    )


class VolumeAccessMode(str, Enum):
    """Access mode for a persistent volume."""

    ReadWriteOnce = "ReadWriteOnce"
    ReadOnlyMany = "ReadOnlyMany"
    ReadWriteMany = "ReadWriteMany"


class PVCVolumeResources(CamelCaseModel):
    """Resources for a persistent volume claim."""

    requests: dict[str, str] = Field(..., title="Resource requests")


class PVCVolumeSource(BaseVolumeSource):
    """A PVC to create to materialize the volume to mount in the container."""

    type: Literal["persistentVolumeClaim"] = Field(
        ..., title="Type of volume to mount"
    )
    access_modes: list[VolumeAccessMode] = Field(..., title="Access mode")
    storage_class_name: str = Field(..., title="Storage class")
    resources: PVCVolumeResources = Field(..., title="Resources for volume")


class LabVolume(CamelCaseModel):
    container_path: str = Field(
        ...,
        example="/home",
        title="Absolute path of the volume mounted inside the Lab container",
        regex="^/.*",
    )
    sub_path: str | None = Field(
        None,
        example="groups",
        title="Mount only this subpath of the volume source",
    )
    mode: FileMode = Field(
        FileMode.RW,
        example="ro",
        title="File permissions when mounted",
        description="`rw` is read/write and `ro` is read-only",
    )
    source: HostPathVolumeSource | NFSVolumeSource | PVCVolumeSource = Field(
        ..., title="Source of volume"
    )


class LabInitContainer(CamelCaseModel):
    name: str = Field(
        ...,
        example="multus-init",
        title="Name of an initContainer run before the user Lab starts",
    )
    image: str = Field(
        ...,
        example="docker.io/lsstit/ddsnet4u:latest",
        title="Docker registry path to initContainer image",
    )
    privileged: bool = Field(
        False,
        example=False,
        title="Whether the initContainer needs privilege to do its job",
        description=(
            "For example, permission to configure networking or "
            "provision filesystems"
        ),
    )
    volumes: list[LabVolume] = Field(
        [],
        title="Volumes mounted by this initContainer",
    )


class LabSecret(CamelCaseModel):
    secret_name: str = Field(
        ...,
        title="Source secret name",
        description=(
            "Must name a secret in the same namespace as the lab controller"
            " pod."
        ),
        example="credentials",
    )
    secret_key: str = Field(
        ...,
        title="Key of source secret within `secret_name`",
        description=(
            "Each secret key must be unique across all secrets in the list"
            " of source secrets, since it is also used as the key for the"
            " entry in the secret created in the user's lab environment."
        ),
        example="butler-credentials",
    )
    env: Optional[str] = Field(
        None,
        title="Environment variable to set to secret value",
        example="BUTLER_CREDENTIALS",
    )
    path: Optional[str] = Field(
        None,
        title="Path inside lab at which to mount secret",
        example="/opt/lsst/software/jupyterlab/butler-secret",
    )


class LabFile(CamelCaseModel):
    contents: str = Field(
        ...,
        example=(
            "root:x:0:0:root:/root:/bin/bash\n"
            "bin:x:1:1:bin:/bin:/sbin/nologin\n",
            "...",
        ),
        title="Contents of file",
    )
    modify: bool = Field(
        False,
        example=False,
        title="Whether to modify this file before injection",
    )


class LabConfig(CamelCaseModel):
    spawn_timeout: timedelta = Field(
        timedelta(minutes=10), title="Timeout for lab spawning"
    )
    sizes: dict[LabSize, LabSizeDefinition] = Field(
        {}, title="Lab sizes users may choose from"
    )
    env: dict[str, str] = Field(
        {}, title="Environment variables to set in user lab"
    )
    secrets: list[LabSecret] = Field(
        [], title="Secrets to make available inside lab"
    )
    files: dict[str, LabFile] = Field({}, title="Files to mount inside lab")
    volumes: list[LabVolume] = Field([], title="Volumes to mount inside lab")
    init_containers: list[LabInitContainer] = Field(
        [], title="Initialization containers to run before user's lab starts"
    )
    pull_secret: Optional[str] = Field(
        None,
        title="Pull secret to use for lab pods",
        description=(
            "If set, must be the name of a secret in the same namespace as"
            " the lab controller. This secret is copied to the user's lab"
            " namespace and referenced as a pull secret in the pod object."
        ),
    )
    namespace_prefix: str = Field(
        default_factory=_get_namespace_prefix,
        title="Namespace prefix for lab environments",
    )
    homedir_schema: UserHomeDirectorySchema = Field(
        UserHomeDirectorySchema.USERNAME,
        title="Schema for user homedir construction",
    )
    extra_annotations: dict[str, str] = Field(
        {},
        title="Extra annotations for lab pod",
    )

    @validator("secrets")
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


#
# Prepuller
#

# See models.v1.prepuller_config

#
# Fileserver
#


class PullPolicy(Enum):
    ALWAYS = "Always"
    IFNOTPRESENT = "IfNotPresent"
    NEVER = "Never"


class FileserverConfig(CamelCaseModel):
    enabled: bool = Field(
        False, title="Whether to enable fileserver capability"
    )
    namespace: str = Field(
        "",
        title="Namespace for user fileservers",
    )
    image: str = Field(
        "",
        example="docker.io/lsstsqre/worblehat",
        title="Docker registry path to fileserver image",
    )
    tag: str = Field(
        "latest", example="0.1.0", title="Tag of fileserver image to use"
    )
    pull_policy: PullPolicy = Field(
        PullPolicy.IFNOTPRESENT,
        example="Always",
        title="Pull policy for the fileserver image",
    )
    timeout: int = Field(
        3600, title="Inactivity timeout for the fileserver container (seconds)"
    )
    path_prefix: str = Field(
        "", title="Fileserver prefix path, to which '/files' is appended"
    )
    resources: Optional[LabResources] = Field(
        None, title="Resource requests and limits"
    )
    creation_timeout: int = Field(
        120, title="Timeout for fileserver creation (seconds)"
    )

    # Only care if our fields are filled out if the fileserver is enabled.
    # Doing it this way saves a lot of assertions about when values
    # are not None down the line.
    @root_validator(pre=True)
    def validate_namespace(cls, values: dict[str, Any]) -> dict[str, Any]:
        enabled = values.get("enabled")
        if enabled:
            for key in ("namespace", "image"):
                if not values.get(key):
                    raise ValueError(f"'{key}' must be specified")
        return values


#
# Config
#


class Config(BaseSettings):
    safir: SafirConfig
    lab: LabConfig
    fileserver: FileserverConfig = Field(
        FileserverConfig(), title="Fileserver configuration"
    )
    images: PrepullerConfig = Field(..., title="Prepuller configuration")
    base_url: str = Field(
        "http://127.0.0.1:8080",
        title="Base URL for Science Platform",
        env="EXTERNAL_INSTANCE_URL",
        description="Injected into the lab pod as EXTERNAL_INSTANCE_URL",
    )
    docker_secrets_path: Path = Field(
        DOCKER_SECRETS_PATH, title="Path to Docker API credentials"
    )
    metadata_path: Path = Field(
        METADATA_PATH,
        title="Path to injected pod metadata",
        description=(
            "This directory should contain files named `name` and `uid`, which"
            " should contain the name and UUID of the lab controller pod,"
            " respectively. (Normally this is done via the Kubernetes"
            " `downwardAPI`.) These are used to set ownership information on"
            " pods spawned by the prepuller."
        ),
    )
    slack_webhook: Optional[str] = Field(
        None,
        title="Slack webhook to which to post alerts",
        env="NUBLADO_SLACK_WEBHOOK",
    )

    # CamelCaseModel conflicts with BaseSettings, so do this manually.
    class Config:
        alias_generator = to_camel_case
        allow_population_by_field_name = True

    @classmethod
    def from_file(cls, path: Path) -> Self:
        """Load the controller configuration from a YAML file."""
        with path.open("r") as f:
            return cls.parse_obj(yaml.safe_load(f))
