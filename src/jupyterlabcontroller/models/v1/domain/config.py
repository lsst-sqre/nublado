from typing import Dict, Union

from pydantic import BaseModel, validator


class SafirConfig(BaseModel):
    name: str
    profile: str
    logger_name: str

    @validator("profile")
    def validate_profile(cls, v: str) -> str:
        assert v in ("production", "development")
        return v


class K8sConfig(BaseModel):
    request_timeout: int


class LabSizeDefinition:
    cpu: float
    memory: Union[int, str]


class LabConfig(BaseModel):
    sizes: Dict[str, LabSizeDefinition]


class Config(BaseModel):
    safir: SafirConfig
    kubernetes: K8sConfig
