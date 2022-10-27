import re
from typing import Dict, List, Optional, TypeAlias, Union

from pydantic import BaseModel, validator

from ..external.prepuller import Config as ExternalPrepullerConfig
from ..external.userdata import UserEnv

#
# Safir
#


class SafirConfig(BaseModel):
    name: str
    profile: str
    logger_name: str

    @validator("profile")
    def validate_profile(cls, v: str) -> str:
        assert v in ("production", "development")
        return v


#
# K8s
#


class K8sConfig(BaseModel):
    request_timeout: int


#
# Lab
#

# https://www.d20srd.org/srd/combat/movementPositionAndDistance.htm#bigandLittleCreaturesInCombat
_srdsizes = (
    "fine",
    "diminutive",
    "tiny",
    "small",
    "medium",
    "large",
    "huge",
    "gargantuan",
    "colossal",
)


class LabSizeDefinition(BaseModel):
    cpu: float
    memory: Union[int, str]


LabSizeDefinitions: TypeAlias = Dict[str, LabSizeDefinition]


class LabSecurityContext(BaseModel):
    runAsUser: int = 1000
    runAsNonRootUser: bool = True
    allowPrivilegeEscalation: bool = False


class LabInitContainer(BaseModel):
    name: str
    image: str
    securityContext: LabSecurityContext


LabInitContainers: TypeAlias = List[LabInitContainer]

# The quota is just the sum of many sizes, effectively
LabQuota = LabSizeDefinition


class LabNFSDefinition(BaseModel):
    path: str
    server: str


class LabVolume(BaseModel):
    name: str
    nfs: LabNFSDefinition


LabVolumes: TypeAlias = List[LabVolume]


class LabVolumeMount(BaseModel):
    name: str
    mountPath: str

    @validator("mountPath")
    def validate_lab_mount_path(cls, v: str) -> str:
        assert v.startswith("/")
        return v


LabVolumeMounts: TypeAlias = List[LabVolumeMount]


class LabFormRestriction(BaseModel):
    type: str
    value: str
    groups: Optional[List[str]] = None

    @validator("type")
    def validate_form_type(cls, v: str) -> str:
        assert v in ("size", "image", "tag")
        return v

    @validator("value")
    def validate_form_value(cls, v: str) -> str:
        _ = re.compile(v)  # Will throw an exception if it's not a valid RE
        return v


LabFormRestrictionList: TypeAlias = List[LabFormRestriction]


class LabForm(BaseModel):
    restrictions: LabFormRestrictionList


class LabFile(BaseModel):
    name: str
    mountPath: str
    contents: str
    modify: bool = False

    @validator("mountPath")
    def validate_lab_mount_path(cls, v: str) -> str:
        assert v.startswith("/")
        return v


LabFiles: TypeAlias = List[LabFile]


class LabConfig(BaseModel):
    sizes: LabSizeDefinitions
    initcontainers: LabInitContainers
    quota: Optional[LabQuota] = None
    volumes: LabVolumes
    volume_mounts: LabVolumeMounts
    env: UserEnv
    form: LabForm
    files: LabFiles

    @validator("sizes")
    def validate_lab_sizes(
        cls, v: Dict[str, LabSizeDefinition]
    ) -> Dict[str, LabSizeDefinition]:
        for sz_name in v.keys():
            assert sz_name in _srdsizes
        return v


#
# Prepuller is the external prepuller Config model
#


class PrepullerConfig(BaseModel):
    config: ExternalPrepullerConfig


#
# Form
#


FormData: TypeAlias = Dict[str, str]

Forms: TypeAlias = Dict[str, FormData]


class FormConfig(BaseModel):
    forms: Forms

    @validator("forms")
    def validate_form(cls, v: FormData) -> FormData:
        assert "default" in v.keys()
        return v


#
# Config
#


class Config(BaseModel):
    safir: SafirConfig
    kubernetes: K8sConfig
    lab: LabConfig
    prepuller: PrepullerConfig
    form: FormConfig
