from __future__ import annotations

from enum import auto
from typing import Any, Dict, List, Optional, TypeAlias, Union

import yaml
from fastapi import Path
from pydantic import BaseModel

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
    name: str
    profile: SafirProfile
    logger_name: str
    log_level: str


#
# Lab
#


class LabSizeDefinition(BaseModel):
    cpu: float = 0.5
    memory: Union[int, str] = "1536MiB"


LabSizeDefinitions: TypeAlias = Dict[LabSize, LabSizeDefinition]


class LabInitContainer(BaseModel):
    name: str
    image: str
    privileged: bool


# The quota is just the sum of many sizes, effectively
LabQuota = LabSizeDefinition


class LabVolume(BaseModel):
    container_path: str = Path(regex="^/*")
    server: str
    server_path: str = Path(regex="^/*")


class LabSecret(BaseModel):
    secret_name: str
    secret_key: str


class LabFile(BaseModel):
    name: str
    mountPath: str = Path(regex="^/*")
    contents: str
    modify: bool = False


class LabConfig(BaseModel):
    sizes: LabSizeDefinitions
    env: Dict[str, str] = {}
    secrets: List[LabSecret] = []
    files: List[LabFile] = []
    volumes: List[LabVolume] = []
    initcontainers: List[LabInitContainer] = []
    quota: Optional[LabQuota] = None


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
