"""Models for jupyterlab-controller."""


from typing import Dict, List

from pydantic import BaseModel, validator

from ..runtime.consts import pod_states, user_statuses

__all__ = ["UserData", "LabSpecification"]


class UserOptions(BaseModel):
    debug: bool = False
    image: str
    reset_user_env: bool = False
    size: str


class UserEnv(BaseModel):
    Dict[str, str]


class UserGroup(BaseModel):
    name: str
    id: int


class UserQuotaQuantum(BaseModel):
    cpu: int
    memory: int


class UserQuota(BaseModel):
    limits: UserQuotaQuantum
    requests: UserQuotaQuantum


class UserData(BaseModel):
    username: str
    status: str
    pod: str
    options: UserOptions
    env: UserEnv
    uid: int
    gid: int
    groups: List[UserGroup]
    quotas: UserQuota

    @validator("status")
    def legal_user_status(cls, v):
        if v not in user_statuses:
            raise ValueError(f"must be one of {user_statuses}")

    @validator("pod")
    def legal_pod_state(cls, v):
        if v not in pod_states:
            raise ValueError(f"must be one of {pod_states}")


class LabSpecification(BaseModel):
    options: UserOptions
    env: UserEnv
