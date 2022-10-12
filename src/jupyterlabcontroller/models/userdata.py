"""Models for jupyterlab-controller."""


from typing import Dict, List

from pydantic import BaseModel

__all__ = ["UserData", "LabSpecification"]


class UserOptions:
    debug: bool = False
    image: str
    reset_user_env: bool = False
    size: str


class UserEnv:
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


class LabSpecification(BaseModel):
    options: UserOptions
    env: UserEnv
