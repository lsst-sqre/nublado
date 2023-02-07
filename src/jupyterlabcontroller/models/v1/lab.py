"""Models for jupyterlab-controller."""
from __future__ import annotations

from collections import deque
from enum import auto
from typing import Deque, Dict, List, Optional

from kubernetes_asyncio.client.models import V1Pod
from pydantic import BaseModel, Field

from ...constants import DROPDOWN_SENTINEL_VALUE
from ...util import str_to_bool
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


class UserOptions(CamelCaseModel):
    """The internal representation of the structure we get from the user POST
    to create a lab.
    """

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


"""POST /nublado/spawner/v1/labs/<username>/create"""


class UserOptionsWireProtocol(BaseModel):
    image_list: List[str] = Field(
        ...,
        name="image_list",
        example=[
            "lighthouse.ceres/library/sketchbook:latest_daily",
            "lighthouse.ceres/library/sketchbook:latest_weekly",
        ],
        title="Images from selection radio button",
    )
    image_dropdown: List[str] = Field(
        ...,
        name="image_dropdown",
        example=[
            "lighthouse.ceres/library/sketchbook@sha256:1234",
            "lighthouse.ceres/library/sketchbook@sha256:5678",
        ],
        title="Images from dropdown list",
    )
    size: List[str] = Field(
        ...,
        name="size",
        example=["small", "medium", "large"],
        title="Image size",
    )
    enable_debug: List[str] = Field(
        ["false"],
        name="enable_debug",
        example=["false"],
        title="Enable debugging in spawned Lab",
    )
    reset_user_env: List[str] = Field(
        ["false"],
        name="reset_user_env",
        example=["false"],
        title="Relocate user environment (.cache, .jupyter, .local)",
    )

    def to_user_options(self) -> UserOptions:
        image = self.image_list[0]
        if image == DROPDOWN_SENTINEL_VALUE:
            image = self.image_dropdown[0]
        return UserOptions(
            image=image,
            size=LabSize(self.size[0].lower()),
            debug=str_to_bool(self.enable_debug[0]),
            reset_user_env=str_to_bool(self.reset_user_env[0]),
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


class LabSpecificationWireProtocol(CamelCaseModel):
    options: UserOptionsWireProtocol
    env: Dict[str, str]
    namespace_quota: Optional[UserResourceQuantum]

    def to_lab_specification(self) -> LabSpecification:
        return LabSpecification(
            options=self.options.to_user_options(),
            env=self.env,
            namespace_quota=self.namespace_quota,
        )


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

    @classmethod
    def from_pod(cls, pod: V1Pod) -> "UserData":
        # We will extract everything from the discovered pod that we need
        # to build a UserData entry.  Size and namespace quota may be
        # incorrect, and group name information and user display name will
        # be lost.
        #
        # We use this when reconciling the user map with the observed state
        # of the world at startup.
        podname = pod.metadata.name
        username = podname[3:]  # Starts with "nb-"
        status = pod.status.phase.lower()
        # pod_state = PodState.PRESENT
        lab_ctr = [x for x in pod.spec.containers if x.name == "notebook"][0]
        if not lab_ctr:
            # try the first container instead...but lab should be "notebook"
            lab_ctr = pod.spec.containers[0]
            # So this will likely crash in extraction
        lab_env_l = lab_ctr.env
        lab_env: Dict[str, str] = dict()
        for ev in lab_env_l:
            lab_env[ev.name] = ev.value or ""  # We will miss reflected vals
        uid = lab_ctr.security_context.run_as_user
        gid = lab_ctr.security_context.run_as_group or uid
        supp_gids = pod.spec.security_context.supplemental_groups or []
        # Now extract enough to get our options and quotas rebuilt
        mem_limit = float(lab_env.get("MEM_LIMIT", 3 * 2**20))
        mem_request = mem_limit / 4
        cpu_limit = float(lab_env.get("CPU_LIMIT", 1.0))
        cpu_request = float(lab_env.get("CPU_GUARANTEE", cpu_limit / 4))
        opt_debug = str_to_bool(lab_env.get("DEBUG", ""))
        opt_image = lab_env.get("JUPYTER_IMAGE_SPEC", "unknown")
        opt_reset_user_env = str_to_bool(lab_env.get("RESET_USER_ENV", ""))
        opt_size = LabSize.SMALL  # We could try harder, but...
        opts = UserOptions(
            debug=opt_debug,
            image=opt_image,
            reset_user_env=opt_reset_user_env,
            size=opt_size,
        )
        # We can't recover the group names
        groups = [{"name": f"g{x}", "id": x} for x in supp_gids]
        user_info = UserInfo(
            username=username,
            name=username,  # We can't recover the display name
            uid=uid,
            gid=gid,
            groups=groups,
        )
        lab_spec = LabSpecification(
            options=opts, env=lab_env, namespace_quota=None
        )
        resources = UserResources(
            limits=UserResourceQuantum(memory=mem_limit, cpu=cpu_limit),
            requests=UserResourceQuantum(memory=mem_request, cpu=cpu_request),
        )
        ud = UserData.new_from_user_resources(
            user=user_info,
            labspec=lab_spec,
            resources=resources,
        )
        ud.status = LabStatus(status)
        ud.pod = PodState.PRESENT
        return ud
