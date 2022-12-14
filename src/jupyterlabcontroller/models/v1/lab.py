"""Models for jupyterlab-controller."""
from __future__ import annotations

from collections import deque
from enum import auto
from typing import Deque, Dict, List, Optional

from pydantic import Field

from ..camelcase import CamelCaseModel
from ..enums import NubladoEnum
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


"""POST /nublado/spawner/v1/labs/<username>/create"""


class UserOptions(CamelCaseModel):
    debug: bool = Field(
        False,
        name="debug",
        example=False,
        title="Whether to enable verbose logging in Lab container",
    )
    image: str = Field(
        ...,
        name="image",
        example="lighthouse.ceres/library/sketchbook:latest_daily",
        title="Full Docker registry path for lab image",
        description="cf. https://docs.docker.com/registry/introduction/",
    )
    reset_user_env: bool = Field(
        False,
        name="reset_user_env",
        example=False,
        title="Whether to relocate user environment data",
        description=(
            "When spawning the lab, move `.cache`, `.local`, and "
            "`.jupyter` directories aside."
        ),
    )
    size: str = Field(
        ...,
        name="size",
        title="Container size descriptor",
        description=(
            "Must be one of the sizes specified at "
            "https://www.d20srd.org/srd/combat/"
            "movementPositionAndDistance.htm#bigandLittleCreaturesInCombat\n"
            "Actual definition of each size is instance-defined"
        ),
    )


class UserResourceQuantum(CamelCaseModel):
    cpu: float = Field(
        ...,
        name="cpu",
        example=1.5,
        title="Kubernetes CPU resource quantity",
        description=(
            "cf. "
            "https://kubernetes.io/docs/tasks/"
            "configure-pod-container/assign-cpu-resource/\n"
        ),
    )
    memory: int = Field(
        ...,
        name="memory",
        example=1073741824,
        title="Kubernetes memory resource in bytes",
    )


class LabSpecification(CamelCaseModel):
    options: UserOptions
    env: Dict[str, str]
    namespace_quota: Optional[UserResourceQuantum]


"""GET /nublado/spawner/v1/labs/<username>"""
"""GET /nublado/spawner/v1/user-status"""


class UserGroup(CamelCaseModel):
    name: str = Field(
        ...,
        name="name",
        example="ferrymen",
        title="Group to which lab user belongs",
        description="Should follow Unix naming conventions",
        regex="^[a-z_][a-z0-9_-]*[$]?$",
    )
    id: int = Field(
        ...,
        name="id",
        example=2023,
        title="Numeric GID of the group (POSIX)",
        description="32-bit unsigned integer",
    )


class UserInfo(CamelCaseModel):
    username: str = Field(
        ...,
        name="username",
        example="ribbon",
        title="Username for Lab user",
        description="Should follow Unix naming conventions",
        regex="^[a-z_][a-z0-9_-]*[$]?$",
    )
    name: str = Field(
        ...,
        name="name",
        example="Ribbon",
        title="Human-friendly display name for user",
        description=(
            "May contain spaces and capital letters; should be the "
            "user's preferred representation of their name to "
            "other humans"
        ),
    )
    uid: int = Field(
        ...,
        name="uid",
        example=1104,
        title="Numeric UID for user (POSIX)",
        description="32-bit unsigned integer",
    )
    gid: int = Field(
        ...,
        name="gid",
        example=1104,
        title="Numeric GID for user's primary group (POSIX)",
        description="32-bit unsigned integer",
    )
    groups: List[UserGroup]


class UserResources(CamelCaseModel):
    limits: UserResourceQuantum = Field(
        ..., name="limits", title="Maximum allowed resources"
    )
    requests: UserResourceQuantum = Field(
        ..., name="requests", title="Intially-requested resources"
    )


class UserData(UserInfo, LabSpecification):
    status: LabStatus = Field(
        ...,
        name="status",
        example="running",
        title="Status of user container.",
        description=(
            "Must be one of `starting`, "
            "`running`, `terminating`, or `failed`."
        ),
    )
    pod: PodState = Field(
        ...,
        name="pod",
        example="present",
        title="User pod state.",
        description="Must be one of `present` or `missing`.",
    )
    resources: UserResources
    events: Deque[Event] = Field(
        deque(),
        name="events",
        title="Ordered queue of events for user lab creation/deletion",
    )

    @classmethod
    def new_from_user_resources(
        cls,
        user: UserInfo,
        labspec: LabSpecification,
        resources: UserResources,
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
            resources=resources,
        )

    @classmethod
    def from_components(
        cls,
        user: UserInfo,
        labspec: LabSpecification,
        resources: UserResources,
        status: LabStatus,
        pod: PodState,
    ) -> "UserData":
        ud = UserData.new_from_user_resources(
            user=user,
            labspec=labspec,
            resources=resources,
        )
        ud.status = status
        ud.pod = pod
        return ud
