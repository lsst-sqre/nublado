from __future__ import annotations

from enum import auto
from typing import Any, Dict, List, Optional, TypeAlias, Union

import yaml
from fastapi import Path
from pydantic import BaseModel, Field

from .models.enum import NubladoEnum
from .models.v1.lab import LabSize
from .models.v1.prepuller_config import PrepullerConfig

#
# Safir
#


class SafirProfile(NubladoEnum):
    PRODUCTION = auto()
    DEVELOPMENT = auto()


class SafirConfig(BaseModel):
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


class LabSizeDefinition(BaseModel):
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


class LabVolume(BaseModel):
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
            "Hostname or IP address of the NFS server providing the " "volume"
        ),
    )
    server_path: str = Path(
        ...,
        name="container_path",
        example="/share1/home",
        description=(
            "Absolute path where the volume is exported from the " "NFS server"
        ),
        regex="^/*",
    )


class LabInitContainer(BaseModel):
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


class LabSecret(BaseModel):
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


class LabFile(BaseModel):
    name: str = Field(
        ...,
        name="name",
        example="passwd",
        description=(
            "Name of file to be mounted into the user Lab container "
            "as a ConfigMap.  This name must be unique, and is used "
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


class LabConfig(BaseModel):
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
# Config
#
class Config(BaseModel):
    safir: SafirConfig
    lab: LabConfig
    prepuller: PrepullerConfig
    path: Optional[str] = None

    @classmethod
    def from_file(
        cls,
        filename: str,
    ) -> Config:
        with open(filename) as f:
            config_obj: Dict[Any, Any] = yaml.safe_load(f)
            # In general the YAML might have configuration for other
            # objects than the controller in it.
            r = Config.parse_obj(config_obj)
            r.path = filename
            return r
