"""Models for jupyterlab-controller."""
from __future__ import annotations

from collections import deque
from copy import copy
from typing import Deque, Dict, List, Tuple, TypeAlias

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
    cpu: float
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
    def legal_user_status(cls, v: str) -> str:
        if v not in lab_statuses:
            raise ValueError(f"must be one of {lab_statuses}")
        return v

    @validator("pod")
    def legal_pod_state(cls, v: str) -> str:
        if v not in pod_states:
            raise ValueError(f"must be one of {pod_states}")
        return v

    def to_components(
        self,
    ) -> Tuple[str, str, UserInfo, LabSpecification, UserQuota]:
        return (
            self.status,
            self.pod,
            UserInfo(
                username=self.username,
                name=self.name,
                uid=self.uid,
                gid=self.gid,
                groups=copy(self.groups),
            ),
            LabSpecification(
                options=copy(self.options),
                env=copy(self.env),
            ),
            UserQuota(
                limits=copy(self.quotas.limits),
                requests=copy(self.quotas.requests),
            ),
        )

    @classmethod
    def from_components(
        cls,
        status: str,
        pod: str,
        user: UserInfo,
        labspec: LabSpecification,
        quotas: UserQuota,
    ) -> UserData:
        return cls(
            status=copy(status),
            pod=copy(pod),
            username=user.username,
            name=user.name,
            uid=user.uid,
            gid=user.gid,
            groups=copy(user.groups),
            options=copy(labspec.options),
            env=copy(labspec.env),
            quotas=UserQuota(
                limits=copy(quotas.limits), requests=copy(quotas.requests)
            ),
        )


UserMap: TypeAlias = Dict[str, UserData]
