"""API-visible models for user lab environments."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional, Self

from pydantic import BaseModel, Field, root_validator, validator

from ...constants import (
    DROPDOWN_SENTINEL_VALUE,
    GROUPNAME_REGEX,
    USERNAME_REGEX,
)

__all__ = [
    "ImageClass",
    "LabSize",
    "LabSpecification",
    "LabStatus",
    "NotebookQuota",
    "PodState",
    "UserGroup",
    "UserInfo",
    "UserLabState",
    "UserOptions",
    "UserQuota",
    "UserResourceQuantum",
    "UserResources",
]


class LabSize(str, Enum):
    """Allowable names for pod sizes.

    Taken from `d20 creature sizes`_.
    """

    FINE = "fine"
    DIMINUTIVE = "diminutive"
    TINY = "tiny"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    HUGE = "huge"
    GARGANTUAN = "gargantuan"
    COLOSSAL = "colossal"

    CUSTOM = "custom"
    """A custom lab size.

    Used for lab sizes of existing labs that don't match any of our
    currently-configured sizes.
    """


class LabStatus(Enum):
    """Possible states the user's lab may be in."""

    PENDING = "pending"
    RUNNING = "running"
    TERMINATING = "terminating"
    FAILED = "failed"

    @classmethod
    def from_phase(cls, phase: str) -> LabStatus:
        """Convert a Kubernetes pod phase to a lab status.

        Be aware that it is not possible to detect Kubernetes pods that are in
        the process of being terminated by looking only at the phase
        (``Terminating`` is not a pod phase). This method will return
        ``RUNNING`` if the container is still running or ``FAILED`` if it has
        stopped.

        Parameters
        ----------
        phase
            Kubernetes pod phase, from the ``Pod`` object.

        Returns
        -------
        LabStatus
            Corresponding lab status.
        """
        if phase == "Running":
            return cls.RUNNING
        elif phase == "Pending":
            return cls.PENDING
        else:
            return cls.FAILED


class PodState(Enum):
    """Possible states the user's pod may be in."""

    PRESENT = "present"
    MISSING = "missing"


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

    @property
    def image_attribute(self) -> str:
        """The name of the image attribute that was set.

        Used for error reporting to know what input attribute to report when
        the image specification was invalid.
        """
        if self.image_list:
            return "image_list"
        elif self.image_dropdown:
            return "image_dropdown"
        elif self.image_class:
            return "image_class"
        else:
            return "image_tag"

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
                if not value:
                    continue
                if len(value) != 1:
                    raise ValueError(f"Too many values for {key}")
                new_values[key] = value[0]
            else:
                new_values[key] = value
        return new_values

    @root_validator
    def _validate_one_image(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Ensure that the image is only specified in one way."""
        values_set = set()
        for k in ("image_list", "image_dropdown", "image_class", "image_tag"):
            if values.get(k) is not None:
                if k == "image_list" and values[k] == DROPDOWN_SENTINEL_VALUE:
                    values[k] = None
                    continue
                values_set.add(k)
        if values_set == {"image_list", "image_dropdown"}:
            # image_dropdown will have a spurious value if image_list is set,
            # due to the form design, so in that case use image_list. (Unless
            # it has the sentinel value, but that's handled above.)
            del values["image_dropdown"]
        elif len(values_set) < 1:
            raise ValueError("No image to spawn specified")
        elif len(values_set) > 1:
            keys = ", ".join(sorted(values_set))
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

    @validator("size", pre=True)
    def _validate_size(cls, v: Any) -> Any:
        """Lab sizes may be title-cased, so convert them to lowercase."""
        if isinstance(v, LabSize):
            return v
        elif isinstance(v, str):
            return v.lower()
        else:
            return v


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
    """Specification of lab to spawn, sent by the JupyterHub spawner."""

    options: UserOptions = Field(
        ...,
        title="User-chosen lab options",
        description="Represents the choices made on the spawner form",
    )
    env: dict[str, str] = Field(
        ...,
        title="Environment variables",
        description=(
            "Environment variables from JupyterHub. JUPYTERHUB_SERVICE_PREFIX"
            " must be set"
        ),
    )

    @validator("env")
    def _validate_env(cls, v: dict[str, str]) -> dict[str, str]:
        if "JUPYTERHUB_SERVICE_PREFIX" not in v:
            raise ValueError("JUPYTERHUB_SERVICE_PREFIX must be set")
        return v


"""GET /nublado/spawner/v1/labs/<username>"""
"""GET /nublado/spawner/v1/user-status"""


class UserGroup(BaseModel):
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


class NotebookQuota(BaseModel):
    """Notebook Aspect quota information for a user."""

    cpu: float = Field(..., title="CPU equivalents", example=4.0)

    memory: float = Field(..., title="Maximum memory use (GiB)", example=16.0)


class UserQuota(BaseModel):
    """Quota information for a user."""

    api: dict[str, int] = Field(
        {},
        title="API quotas",
        description=(
            "Mapping of service names to allowed requests per 15 minutes."
        ),
        example={
            "datalinker": 500,
            "hips": 2000,
            "tap": 500,
            "vo-cutouts": 100,
        },
    )

    notebook: Optional[NotebookQuota] = Field(
        None, title="Notebook Aspect quotas"
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
            "May contain spaces, capital letters, and non-ASCII characters."
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
    quota: Optional[UserQuota] = Field(None, title="User's quotas")


class UserResources(BaseModel):
    limits: UserResourceQuantum = Field(..., title="Maximum allowed resources")
    requests: UserResourceQuantum = Field(
        ..., title="Intially-requested resources"
    )


class UserLabState(UserInfo, LabSpecification):
    """Current state of the user's lab."""

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
    internal_url: Optional[str] = Field(
        None,
        example="http://nublado-ribbon.nb-ribbon:8888",
        title="URL by which the Hub can access the user Pod",
    )
    resources: UserResources = Field(..., title="Resource requests and limits")

    @classmethod
    def new_from_user_resources(
        cls,
        user: UserInfo,
        labspec: LabSpecification,
        resources: UserResources,
    ) -> Self:
        return cls(
            options=labspec.options,
            env=labspec.env,
            status=LabStatus.PENDING,
            pod=PodState.MISSING,
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
    ) -> Self:
        ud = cls.new_from_user_resources(
            user=user,
            labspec=labspec,
            resources=resources,
        )
        ud.status = status
        ud.pod = pod
        return ud
