"""Models for jupyterlab-controller."""
from __future__ import annotations

from collections import deque
from copy import copy
from enum import auto
from typing import Deque, Dict, List, Tuple, TypeAlias

from pydantic import BaseModel, Field

from ..enum import NubladoEnum
from .event import Event


class LabSize(NubladoEnum):
    # https://www.d20srd.org/srd/combat/movementPositionAndDistance.htm#bigandLittleCreaturesInCombat
    FINE = auto()
    DIMINUTIVE = auto()
    TINY = auto()
    SMALL = auto()
    MEDIUM = auto()
    LARGE = auto()
    HUGE = auto()
    GARGANTUAN = auto()
    COLOSSAL = auto()


class LabStatus(NubladoEnum):
    STARTING = auto()
    RUNNING = auto()
    TERMINATING = auto()
    FAILED = auto()


class PodState(NubladoEnum):
    PRESENT = auto()
    MISSING = auto()


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
    env: Dict[str, str]


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
    status: LabStatus = Field(
        ...,
        title="status",
        example="running",
        description=(
            "Status of user container.  Must be one of `starting`,"
            " `running`, `terminating`, or `failed`."
        ),
    )
    pod: PodState = Field(
        ...,
        title="pod",
        example="present",
        description=(
            "User pod state.  Must be one of `present` or `missing`."
        ),
    )
    quota: UserQuota
    events: Deque[Event] = Field(
        deque(),
        title="events",
        description=("Ordered queue of events for user lab creation/deletion"),
    )

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
                limits=copy(self.quota.limits),
                requests=copy(self.quota.requests),
            ),
        )

    @classmethod
    def new_from_user_lab_quota(
        cls,
        user: UserInfo,
        labspec: LabSpecification,
        quota: UserQuota,
    ) -> "UserData":
        return cls(
            username=user.username,
            name=user.name,
            uid=user.uid,
            gid=user.gid,
            groups=user.groups,
            options=labspec.options,
            env=labspec.env,
            events=deque(),
            status="starting",
            pod="missing",
            quota=quota,
        )

    @classmethod
    def from_components(
        cls,
        user: UserInfo,
        labspec: LabSpecification,
        quota: UserQuota,
        status: LabStatus,
        pod: PodState,
    ) -> "UserData":
        ud = UserData.new_from_user_lab_quota(
            user=user, labspec=labspec, quota=quota
        )
        ud.status = status
        ud.pod = pod
        return ud
