"""Models for jupyterlab-controller."""
from __future__ import annotations

from collections import deque
from copy import copy
from typing import Deque, List, Tuple, TypeAlias

from pydantic import BaseModel, Field, validator

from ..consts import lab_statuses, pod_states
from .event import Event
from .lab_userenv import UserEnv

"""GET /nublado/spawner/v1/labs"""
RunningLabUsers: TypeAlias = List[str]


"""POST /nublado/spawner/v1/labs/<username>/create"""


class UserOptions(BaseModel):
    debug: bool = Field(
        False,
        title="Debug",
        example=False,
        description="Enable verbose logging in spawned Lab container",
    )
    image: str = Field(
        ...,
        title="Lab container image",
        example="lighthouse.ceres/library/sketchbook:latest_daily",
        description=(
            "Full Docker registry path (cf."
            " https://docs.docker.com/registry/introduction/ )"
            " for lab image."
        ),
    )
    reset_user_env: bool = Field(
        False,
        title="Reset user environment",
        example=False,
        description=(
            "When spawning the lab, move `.cache`, `.local`, and"
            " `.jupyter` directories aside."
        ),
    )
    size: str = Field(
        ...,
        title="Container size",
        description=(
            "Container size descriptor.  Must be one of the sizes"
            " specified at"
            " https://www.d20srd.org/srd/combat/"
            "movementPositionAndDistance.htm#bigandLittleCreaturesInCombat\n"
            "Actual definition of each size is instance-defined."
        ),
    )


class LabSpecification(BaseModel):
    options: UserOptions
    env: UserEnv


"""GET /nublado/spawner/v1/labs/<username>"""
"""GET /nublado/spawner/v1/user-status"""


class UserGroup(BaseModel):
    name: str = Field(
        ...,
        title="name",
        example="ferrymen",
        description=(
            "Group to which lab user belongs.  Should follow general"
            " Unix naming conventions and therefore match the regular"
            " expression `[a-z_][a-z0-9_-]*[$]` ."
        ),
    )
    id: int = Field(
        ...,
        title="id",
        example=2023,
        description=(
            "Numeric GID of the group (POSIX).  32-bit unsigned " " integer."
        ),
    )


UserGroupList: TypeAlias = List[UserGroup]


class UserInfo(BaseModel):
    username: str = Field(
        ...,
        title="username",
        example="ribbon",
        description=(
            "Username for Lab user.  Should follow general Unix"
            " naming conventions and therefore match the regular"
            " expression `[a-z_][a-z0-9_-]*[$]` ."
        ),
    )
    name: str = Field(
        ...,
        title="name",
        example="Ribbon",
        description=(
            "Human-friendly display name for user.  May contain"
            " contain spaces and capital letters; should be the"
            " user's preferred representation of their name to"
            " other humans."
        ),
    )
    uid: int = Field(
        ...,
        title="uid",
        example=1104,
        description=(
            "Numeric UID for user (POSIX).  32-bit unsigned integer."
        ),
    )
    gid: int = Field(
        ...,
        title="gid",
        example=1104,
        description=(
            "Numeric GID for user's primary group (POSIX).  32-bit"
            " unsigned integer."
        ),
    )
    groups: UserGroupList


class UserQuotaQuantum(BaseModel):
    cpu: float = Field(
        ...,
        title="cpu",
        example=1.5,
        description=(
            "Kubernetes CPU resource, floating-point value.  cf"
            " https://kubernetes.io/docs/tasks/configure-pod-container/"
            "assign-cpu-resource/"
        ),
    )
    memory: int = Field(
        ...,
        title="memory",
        example=1073741824,
        description=("Kubernetes memory resource in bytes."),
    )


class UserQuota(BaseModel):
    limits: UserQuotaQuantum = Field(
        ..., title="limits", description="Maximum allowed resources"
    )
    requests: UserQuotaQuantum = Field(
        ..., title="requests", description="Intially-requested resources"
    )


class UserData(UserInfo, LabSpecification):
    status: str = Field(
        ...,
        title="status",
        example="running",
        description=(
            "Status of user container.  Must be one of `starting`,"
            " `running`, `terminating`, or `failed`."
        ),
    )
    pod: str = Field(
        ...,
        title="pod",
        example="present",
        description=(
            "User pod state.  Must be one of `present` or `missing`."
        ),
    )
    quotas: UserQuota
    events: Deque[Event] = Field(
        deque(),
        title="events",
        description=("Ordered queue of events for user lab creation/deletion"),
    )

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
