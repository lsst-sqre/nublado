from __future__ import annotations

import os
from enum import auto
from typing import Dict, List, TypeAlias

import yaml
from fastapi import Path
from pydantic import Field
from safir.logging import LogLevel, Profile
from safir.pydantic import CamelCaseModel

from .models.enums import NubladoEnum
from .models.v1.lab import LabSize
from .models.v1.prepuller_config import PrepullerConfiguration

#
# Safir
#


class SafirConfiguration(CamelCaseModel):
    name: str = Field(
        ...,
        name="name",
        example="jupyterlab-controller",
        title=(
            "Application name (not necessarily the root HTTP endpoint path)"
        ),
    )
    root_endpoint: str = Field(
        ...,
        name="root_endpoint",
        example="nublado",
        title="Application root HTTP endpoint path",
    )
    profile: Profile = Field(
        "production",
        name="profile",
        example="production",
        title="Application run profile, either 'production' or 'development'",
    )
    logger_name: str = Field(
        ...,
        name="logger_name",
        example="jupyterlabcontroller",
        title="Root name of the application's logger",
    )
    log_level: LogLevel = Field(
        "INFO",
        name="log_level",
        example="INFO",
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


LabSizeDefinitions: TypeAlias = Dict[LabSize, LabSizeDefinition]


class FileMode(NubladoEnum):
    RW = auto()
    RO = auto()


class LabVolume(CamelCaseModel):
    container_path: str = Path(
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
    server_path: str = Path(
        ...,
        name="server_path",
        example="/share1/home",
        title="Absolute path where the volume is exported from the NFS server",
        regex="^/*",
    )
    mode: FileMode = Field(
        FileMode("rw"),
        name="mode",
        example="rw",
        title="File mode: 'rw' is read/write and 'ro' is read-only",
        regex="^r[ow]$",
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
    volumes: List[LabVolume] = Field(
        list(),
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
    sizes: LabSizeDefinitions
    env: Dict[str, str] = Field(default_factory=dict)
    secrets: List[LabSecret] = Field(default_factory=list)
    files: Dict[str, LabFile] = Field(default_factory=list)
    volumes: List[LabVolume] = Field(default_factory=list)
    init_containers: List[LabInitContainer] = Field(default_factory=list)


#
# Prepuller
#

# See models.v1.prepuller_config

#
# Runtime
# filled in at runtime, obv.
# If set, will be ignored.
#
class RuntimeConfiguration(CamelCaseModel):
    path: str = ""
    namespace_prefix: str = ""
    instance_url: str = ""

    # FIXME: Don't understand why forcing values in validator isn't working.


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
            r = Configuration.parse_obj(yaml.safe_load(f))
        ns_prefix = os.getenv("USER_NAMESPACE_PREFIX", "")
        if not ns_prefix:
            ns_path = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"
            if os.path.exists(ns_path):
                with open(ns_path) as f:
                    ns_prefix = f.read().strip()
            else:
                ns_prefix = "userlabs"

        r.runtime = RuntimeConfiguration(
            path=filename,
            instance_url=os.getenv(
                "EXTERNAL_INSTANCE_URL", "http://127.0.0.1:8080"
            ),
            namespace_prefix=ns_prefix,
        )
        return r
