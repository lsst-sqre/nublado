from __future__ import annotations

from typing import Any, Dict, List, Optional, TypeAlias, Union

import yaml
from pydantic import BaseModel, validator

from .models.enums import lab_sizes
from .models.v1.lab import UserEnv
from .models.v1.prepuller_config import PrepullerConfig

#
# Safir
#


class SafirConfig(BaseModel):
    name: str
    profile: str
    logger_name: str
    log_level: str

    @validator("profile")
    def validate_profile(cls, v: str) -> str:
        assert v in ("production", "development")
        return v


#
# Lab
#


class LabSizeDefinition(BaseModel):
    cpu: float = 0.5
    memory: Union[int, str] = "1536MiB"


LabSizeDefinitions: TypeAlias = Dict[str, LabSizeDefinition]


class LabInitContainer(BaseModel):
    name: str
    image: str
    privileged: bool


# The quota is just the sum of many sizes, effectively
LabQuota = LabSizeDefinition


class LabVolume(BaseModel):
    container_path: str
    server: str
    server_path: str


class LabSecret(BaseModel):
    secret_name: str
    secret_key: str


class LabFile(BaseModel):
    name: str
    mountPath: str
    contents: str
    modify: bool = False

    @validator("mountPath")
    def validate_lab_mount_path(cls, v: str) -> str:
        assert v.startswith("/")
        return v


class LabConfig(BaseModel):
    sizes: LabSizeDefinitions
    env: UserEnv = {}
    secrets: List[LabSecret] = []
    files: List[LabFile] = []
    volumes: List[LabVolume] = []
    initcontainers: List[LabInitContainer] = []
    quota: Optional[LabQuota] = None

    @validator("sizes")
    def validate_lab_sizes(
        cls, v: Dict[str, LabSizeDefinition]
    ) -> Dict[str, LabSizeDefinition]:
        for sz_name in v.keys():
            assert sz_name in lab_sizes
        return v


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
