"""Models for jupyterlab-controller."""

from collections import deque
from enum import Enum, auto
from typing import Any, Deque, Dict, Optional

from kubernetes_asyncio.client.models import V1Pod
from pydantic import BaseModel, Field, root_validator, validator
from safir.pydantic import CamelCaseModel

from ...constants import (
    DROPDOWN_SENTINEL_VALUE,
    GROUPNAME_REGEX,
    USERNAME_REGEX,
)
from ...util import str_to_bool
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
    PENDING = auto()
    RUNNING = auto()
    TERMINATING = auto()
    FAILED = auto()


class PodState(NubladoEnum):
    PRESENT = auto()
    MISSING = auto()


"""POST /nublado/spawner/v1/labs/<username>/create"""


class ImageClass(Enum):
    """Supported classes of images.

    These keywords can be passed into the spawn form to spawn whatever image
    matches this class, as determined by the lab controller. This is primarily
    used when spawning notebooks for bot users.
    """

    RECOMMENDED = "recommended"
    LATEST_RELEASE = "latest-release"
    LATEST_WEEKLY = "latest-weekly"
    LATEST_DAILY = "latest-daily"


class UserOptions(BaseModel):
    """User-provided lab configuration options.

    All values to this model can instead be given as lists of length one with
    boolean values converted to the strings ``true`` or ``false``. This allows
    JupyterHub to pass its form submission directly to the lab controller
    without modifications.
    """

    image_list: Optional[str] = Field(
        None,
        example="lighthouse.ceres/library/sketchbook:w_2023_07@sha256:abcd",
        title="Image from selection radio button",
        description="If this is set, `image_dropdown` should not be set.",
    )
    image_dropdown: Optional[str] = Field(
        None,
        example="lighthouse.ceres/library/sketchbook:w_2022_40",
        title="Image from dropdown list",
        description=(
            "If this is set, `image_list` should be omitted or set to"
            f" `{DROPDOWN_SENTINEL_VALUE}`."
        ),
    )
    image_class: Optional[ImageClass] = Field(
        None,
        example=ImageClass.RECOMMENDED,
        title="Class of image to spawn",
        description=(
            "Spawn a class of image determined by the lab controller. Not"
            " used by the user form, but may be used by bots creating labs."
            " Only one of `image_class` or `image_tag` may be given, and"
            " neither `image_list` nor `image_dropdown` should be set when"
            " using these options."
        ),
    )
    image_tag: Optional[str] = Field(
        None,
        example="w_2023_07",
        title="Tag of image to spawn",
        description=(
            "Spawn the image with the given tag. Not used by the user form,"
            " but may be used by bots creating labs. Only one of `image_class`"
            " `image_tag` may be given, and neither `image_list` nor"
            " `image_dropdown` should be set when using these options."
        ),
    )
    size: LabSize = Field(..., example=LabSize.MEDIUM, title="Image size")
    enable_debug: bool = Field(
        False,
        example=True,
        title="Enable debugging in spawned Lab",
    )
    reset_user_env: bool = Field(
        False,
        example=True,
        title="Relocate user environment (`.cache`, `.jupyter`, `.local`)",
    )

    class Config:
        # Tell Pydantic's dict() method to convert the size enum to a string.
        # This doesn't matter for FastAPI responses, since this is always done
        # for JSON encoding, but it makes test suite construction easier.
        use_enum_values = True

    @root_validator(pre=True)
    def _validate_lists(cls, values: dict[str, Any]) -> dict[str, list[Any]]:
        """Convert from lists of length 1 to values.

        JupyterHub passes the value of the input form directly to the lab
        controller via this model. This means that each submitted field is a
        list, due to implementation details of JupyterHub, but in each case
        the list must have exactly one element and we don't want the list
        wrapper. Also accept values without the list wrapping for direct calls
        to the lab controller via the same API.
        """
        new_values = {}
        for key, value in values.items():
            if value is None:
                continue
            if isinstance(value, list):
                if len(value) != 1:
                    raise ValueError(f"Too many values for {key}")
                new_values[key] = value[0]
            else:
                new_values[key] = value
        return new_values

    @root_validator
    def _validate_one_image(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Ensure that the image is only specified in one way."""
        values_set = []
        for k in ("image_list", "image_dropdown", "image_class", "image_tag"):
            if values.get(k) is not None:
                if k == "image_list" and values[k] == DROPDOWN_SENTINEL_VALUE:
                    del values[k]
                    continue
                values_set.append(k)
        if len(values_set) < 1:
            raise ValueError("No image to spawn specified")
        elif len(values_set) > 1:
            keys = ", ".join(values_set)
            raise ValueError(f"Image specified multiple ways ({keys})")
        return values

    @validator("enable_debug", "reset_user_env", pre=True)
    def _validate_booleans(cls, v: bool | str) -> bool:
        """Convert boolean values from strings."""
        if isinstance(v, bool):
            return v
        elif v == "true":
            return True
        elif v == "false":
            return False
        else:
            raise ValueError(f"Invalid boolean value {v}")


class UserResourceQuantum(BaseModel):
    cpu: float = Field(
        ...,
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
        example=1073741824,
        title="Kubernetes memory resource in bytes",
    )


class LabSpecification(BaseModel):
    options: UserOptions = Field(..., title="User-chosen lab options")
    env: dict[str, str] = Field(
        ..., title="Environment variables from JupyterHub"
    )
    namespace_quota: Optional[UserResourceQuantum] = Field(
        None, title="Quota for user"
    )


"""GET /nublado/spawner/v1/labs/<username>"""
"""GET /nublado/spawner/v1/user-status"""


class UserGroup(CamelCaseModel):
    name: str = Field(
        ...,
        example="ferrymen",
        title="Group to which lab user belongs",
        description="Should follow Unix naming conventions",
        regex=GROUPNAME_REGEX,
    )
    id: Optional[int] = Field(
        None,
        example=2023,
        title="Numeric GID of the group (POSIX)",
        description="32-bit unsigned integer",
    )


class UserInfo(BaseModel):
    username: str = Field(
        ...,
        example="ribbon",
        title="Username for Lab user",
        regex=USERNAME_REGEX,
    )
    name: str = Field(
        ...,
        example="Ribbon",
        title="Human-friendly display name for user",
        description=(
            "May contain spaces, capital letters, and non-ASCII characters"
            " Should be the user's preferred representation of their name to"
            " other humans."
        ),
    )
    uid: int = Field(
        ...,
        example=1104,
        title="Numeric UID for user (POSIX)",
        description="32-bit unsigned integer",
    )
    gid: int = Field(
        ...,
        example=1104,
        title="Numeric GID for user's primary group (POSIX)",
        description="32-bit unsigned integer",
    )
    groups: list[UserGroup] = Field([], title="User's group memberships")


class UserResources(CamelCaseModel):
    limits: UserResourceQuantum = Field(..., title="Maximum allowed resources")
    requests: UserResourceQuantum = Field(
        ..., title="Intially-requested resources"
    )


class UserData(UserInfo, LabSpecification):
    status: LabStatus = Field(
        ...,
        example="running",
        title="Status of user container.",
        description=(
            "Must be one of `pending`, "
            "`running`, `terminating`, or `failed`."
        ),
    )
    pod: PodState = Field(
        ...,
        example="present",
        title="User pod state.",
        description="Must be one of `present` or `missing`.",
    )
    resources: UserResources = Field(..., title="Resource requests and limits")
    events: Deque[Event] = Field(
        deque(),
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
            options=labspec.options,
            env=labspec.env,
            events=deque(),
            status="pending",
            pod="missing",
            resources=resources,
            **user.dict(),
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
        opt_reference = lab_env.get("JUPYTER_IMAGE_SPEC", "unknown")
        opt_reset_user_env = str_to_bool(lab_env.get("RESET_USER_ENV", ""))
        opt_size = LabSize.SMALL  # We could try harder, but...
        opts = UserOptions(
            debug=opt_debug,
            image=opt_reference,
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
