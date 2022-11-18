from __future__ import annotations

import os
from enum import auto
from typing import Any, Dict, List, Optional, TypeAlias, Union

import yaml
from fastapi import Path
from pydantic import Field

from .models.camelcase import CamelCaseModel
from .models.enum import NubladoEnum
from .models.v1.lab import LabSize
from .models.v1.prepuller_config import PrepullerConfiguration


def get_namespace_prefix() -> str:
    """If USER_NAMESPACE_PREFIX is set in the environment, that will be used as
    the namespace prefix.  If it is not, the namespace will be read from the
    container.  If that the container runtime file does not exist, "userlabs"
    will be used.
    """
    r: str = os.getenv("USER_NAMESPACE_PREFIX", "")
    if r:
        return r
    ns_path = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"
    if os.path.exists(ns_path):
        with open(ns_path) as f:
            return f.read().strip()
    return "userlabs"


def get_external_instance_url() -> str:
    """In normal operation, EXTERNAL_INSTANCE_URL will have been set from
    a global in the Helm chart.  For testing, or if running standalone,
    either set that URL, or assume you're listening on localhost port 8080.
    """
    return os.getenv("EXTERNAL_INSTANCE_URL") or "http://localhost:8080"


#
# Safir
#


class SafirProfile(NubladoEnum):
    PRODUCTION = auto()
    DEVELOPMENT = auto()


class SafirConfiguration(CamelCaseModel):
    name: str = Field(
        ...,
        title="name",
        example="jupyterlab-controller",
        description=(
            "Application name (not necessarily the root " "endpoint path)"
        ),
    )
    profile: SafirProfile = Field(
        ...,
        title="profile",
        example="production",
        description=(
            "Application run profile, either 'production' " "or 'development'"
        ),
    )
    logger_name: str = Field(
        ...,
        title="logger_name",
        example="jupyterlabcontroller",
        description="Root name of the application's logger",
    )
    log_level: str = Field(
        ...,
        title="log_level",
        example="INFO",
        description="String representing the default log level",
    )


#
# Lab
#


class LabSizeDefinition(CamelCaseModel):
    cpu: float = Field(
        ...,
        title="cpu",
        example=0.5,
        description=(
            "Number of CPU resource units for Lab container.  See "
            "https://kubernetes.io/docs/concepts/configuration/"
            "manage-resources-containers/"
        ),
    )
    memory: Union[int, str] = Field(
        ...,
        title="memory",
        example="1536MiB",
        description=(
            "Amount of memory for Lab container.  May be specified "
            "as a text string (e.g. '1536Mib') or as an integer "
            "representing the number of bytes"
        ),
    )


LabSizeDefinitions: TypeAlias = Dict[LabSize, LabSizeDefinition]


class FileMode(NubladoEnum):
    RW = auto()
    RO = auto()


class LabVolume(CamelCaseModel):
    container_path: str = Path(
        ...,
        name="container_path",
        example="/home",
        description=(
            "Absolute path where the volume is mounted inside the "
            "Lab container"
        ),
        regex="^/*",
    )
    server: str = Field(
        ...,
        name="server",
        example="10.13.105.122",
        description=(
            "Hostname or IP address of the NFS server providing the volume.  "
            "If it is the empty string, the mount is taken to be of type "
            "HostPath rather than NFS."
        ),
    )
    server_path: str = Path(
        ...,
        name="container_path",
        example="/share1/home",
        description=(
            "Absolute path where the volume is exported from the NFS server"
        ),
        regex="^/*",
    )
    mode: FileMode = Field(
        FileMode("rw"),
        name="mode",
        example="rw",
        description=(
            "File mode: 'rw' means read/write, while 'ro' means read only.  "
            "The default is read/write."
        ),
    )


class LabInitContainer(CamelCaseModel):
    name: str = Field(
        ...,
        title="name",
        example="multus-init",
        description="Name of an initContainer run before the user Lab starts",
    )
    image: str = Field(
        ...,
        title="image",
        example="docker.io/lsstit/ddsnet4u:latest",
        description="Docker registry path to initContainer image",
    )
    privileged: bool = Field(
        False,
        title="privileged",
        example=False,
        description=(
            "Whether the initContainer needs privilege to do its "
            "job (e.g., configure networking or provision "
            "filesystems)"
        ),
    )
    volumes: Optional[List[LabVolume]] = Field(
        None,
        title="volumes",
        description="Volumes mounted by this initContainer",
    )


class LabSecret(CamelCaseModel):
    secret_name: str = Field(
        ...,
        name="secret_name",
        example="credentials",
        description=(
            "Name of secret in Lab controller namespace from which "
            " secrets will be be copied into user Lab namespace"
        ),
    )
    secret_key: str = Field(
        ...,
        name="secret_key",
        example="butler-credentials",
        description=(
            "Name of key within secret given by secret_name of "
            "secret to be copied into user Lab namespace.  Note that "
            "it is the values file maintainer's responsibility to "
            "ensure there is no collision between key names"
        ),
    )


class LabFile(CamelCaseModel):
    name: str = Field(
        ...,
        name="name",
        example="passwd",
        description=(
            "Name of file to be mounted into the user Lab container "
            "as a ConfigurationMap.  This name must be unique, and is used "
            "if modify is True to signal the lab controller how the "
            "file needs modification before injection into the "
            "container"
        ),
    )
    mount_path: str = Path(
        ...,
        name="mount_path",
        example="/home",
        description=(
            "Absolute path where the file will be mounted into the "
            "Lab container"
        ),
        regex="^/*",
    )
    contents: str = Field(
        ...,
        name="contents",
        example=(
            "root:x:0:0:root:/root:/bin/bash\n"
            "bin:x:1:1:bin:/bin:/sbin/nologin\n",
            "...",
        ),
        description="Contents of file",
    )
    modify: bool = Field(
        False,
        name="modify",
        example=False,
        description="Whether to modify this file before injection",
    )


class LabConfiguration(CamelCaseModel):
    sizes: LabSizeDefinitions
    env: Dict[str, str] = Field(default_factory=dict)
    secrets: List[LabSecret] = Field(default_factory=list)
    files: List[LabFile] = Field(default_factory=list)
    volumes: List[LabVolume] = Field(default_factory=list)
    initcontainers: List[LabInitContainer] = Field(default_factory=list)


#
# Prepuller
#

# See models.v1.prepuller_config

#
# Runtime
# filled in at runtime, obv.
# Not available to users to set.
#
class RuntimeConfiguration(CamelCaseModel):
    path: str = ""
    namespace_prefix: str = ""
    instance_url: str = ""


#
# Configuration
#


class Configuration(CamelCaseModel):
    safir: SafirConfiguration
    lab: LabConfiguration
    images: PrepullerConfiguration
    runtime: RuntimeConfiguration

    @classmethod
    def from_file(
        cls,
        filename: str,
    ) -> Configuration:
        with open(filename) as f:
            config_obj: Dict[Any, Any] = yaml.safe_load(f)
            # In general the YAML might have configuration for other
            # objects than the controller in it.
            r = Configuration.parse_obj(config_obj)
            r.runtime = RuntimeConfiguration(
                path=filename,
                namespace_prefix=get_namespace_prefix(),
                instance_url=get_external_instance_url(),
            )
            return r
