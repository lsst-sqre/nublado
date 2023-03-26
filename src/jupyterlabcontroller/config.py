"""Global configuration parsing."""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseSettings, Field
from safir.logging import LogLevel, Profile
from safir.pydantic import CamelCaseModel, to_camel_case

from .constants import DOCKER_SECRETS_PATH
from .models.v1.lab import LabSize
from .models.v1.prepuller_config import PrepullerConfiguration


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


class SafirConfiguration(CamelCaseModel):
    """Configuration common to most Safir-based applications."""

    name: str = Field(
        "nublado",
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
        name="cpu",
        title="Number of CPU resource units for container",
        example=0.5,
        description=(
            "See https://kubernetes.io/docs/concepts/configuration/"
            "manage-resources-containers/"
        ),
    )
    memory: str = Field(
        ...,
        name="memory",
        title="Amount of memory for Lab container.",
        example="1536MiB",
        description="Must be specified as a text string (e.g. '1536MiB')",
    )


class FileMode(Enum):
    """Possible read/write modes with which a file may be mounted."""

    RW = "rw"
    RO = "ro"


class LabVolume(CamelCaseModel):
    container_path: str = Field(
        ...,
        name="container_path",
        example="/home",
        title="Absolute path of the volume mounted inside the Lab container",
        regex="^/*",
    )
    server: str = Field(
        ...,
        name="server",
        example="10.13.105.122",
        title="Name or address of the server providing the volume",
        description=(
            "If 'server' is the empty string, the mount is taken to be of "
            "type HostPath rather than NFS"
        ),
    )
    server_path: str = Field(
        ...,
        name="server_path",
        example="/share1/home",
        title="Absolute path where the volume is exported from the NFS server",
        regex="^/*",
    )
    mode: FileMode = Field(
        FileMode.RW,
        name="mode",
        example="ro",
        title="File permissions when mounted",
        description="`rw` is read/write and `ro` is read-only",
    )


class LabInitContainer(CamelCaseModel):
    name: str = Field(
        ...,
        name="name",
        example="multus-init",
        title="Name of an initContainer run before the user Lab starts",
    )
    image: str = Field(
        ...,
        name="image",
        example="docker.io/lsstit/ddsnet4u:latest",
        title="Docker registry path to initContainer image",
    )
    privileged: bool = Field(
        False,
        name="privileged",
        example=False,
        title="Whether the initContainer needs privilege to do its job",
        description=(
            "For example, permission to configure networking or "
            "provision filesystems"
        ),
    )
    volumes: list[LabVolume] = Field(
        [],
        name="volumes",
        title="Volumes mounted by this initContainer",
    )


class LabSecret(CamelCaseModel):
    secret_name: str = Field(
        ...,
        name="secret_name",
        example="credentials",
        title="Name of source secret in Lab controller namespace",
    )
    secret_key: str = Field(
        ...,
        name="secret_key",
        example="butler-credentials",
        title="Key of source secret within secret_name",
        description=(
            "Note that it is the values file maintainer's "
            "responsibility to ensure there is no collision "
            "between key names"
        ),
    )


class LabFile(CamelCaseModel):
    contents: str = Field(
        ...,
        name="contents",
        example=(
            "root:x:0:0:root:/root:/bin/bash\n"
            "bin:x:1:1:bin:/bin:/sbin/nologin\n",
            "...",
        ),
        title="Contents of file",
    )
    modify: bool = Field(
        False,
        name="modify",
        example=False,
        title="Whether to modify this file before injection",
    )


class LabConfiguration(CamelCaseModel):
    sizes: dict[LabSize, LabSizeDefinition] = {}
    env: dict[str, str] = {}
    secrets: list[LabSecret] = []
    files: dict[str, LabFile] = {}
    volumes: list[LabVolume] = []
    init_containers: list[LabInitContainer] = []
    namespace_prefix: str = Field(
        default_factory=_get_namespace_prefix,
        title="Namespace prefix for lab environments",
    )


#
# Prepuller
#

# See models.v1.prepuller_config


#
# Configuration
#


class Configuration(BaseSettings):
    safir: SafirConfiguration
    lab: LabConfiguration
    images: PrepullerConfiguration

    base_url: str = Field(
        "http://127.0.0.1:8080",
        title="Base URL for Science Platform",
        env="EXTERNAL_INSTANCE_URL",
        description="Injected into the lab pod as EXTERNAL_INSTANCE_URL",
    )
    docker_secrets_path: Path = Field(
        DOCKER_SECRETS_PATH, title="Path to Docker API credentials"
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
