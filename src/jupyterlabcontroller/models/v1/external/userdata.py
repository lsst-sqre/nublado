"""Models for jupyterlab-controller."""

from collections import deque
from typing import Deque, Dict, List, TypeAlias

from pydantic import BaseModel, validator

from ..consts import lab_statuses, pod_states
from .event import Event


class UserOptions(BaseModel):
    debug: bool = False
    image: str
    reset_user_env: bool = False
    size: str


UserEnv: TypeAlias = Dict[str, str]


class UserGroup(BaseModel):
    name: str
    id: int


class UserQuotaQuantum(BaseModel):
    cpu: int
    memory: int


class UserQuota(BaseModel):
    limits: UserQuotaQuantum
    requests: UserQuotaQuantum


class UserInfo(BaseModel):
    username: str
    name: str
    uid: int
    gid: int
    groups: List[UserGroup]


class LabSpecification(BaseModel):
    options: UserOptions
    env: UserEnv


class UserData(UserInfo, LabSpecification):
    status: str
    pod: str
    quotas: UserQuota
    events: Deque[Event] = deque()

    @validator("status")
    def legal_user_status(cls, v: str) -> None:
        if v not in lab_statuses:
            raise ValueError(f"must be one of {lab_statuses}")

    @validator("pod")
    def legal_pod_state(cls, v: str) -> None:
        if v not in pod_states:
            raise ValueError(f"must be one of {pod_states}")


UserMap: TypeAlias = Dict[str, UserData]
