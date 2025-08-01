"""API-visible models for user lab environments."""

from __future__ import annotations

from enum import Enum, StrEnum
from typing import Annotated, Any, Self

from kubernetes_asyncio.client import V1ResourceRequirements
from pydantic import (
    BaseModel,
    BeforeValidator,
    Field,
    field_validator,
    model_validator,
)

from ...constants import DROPDOWN_SENTINEL_VALUE, USERNAME_REGEX
from ...units import memory_to_bytes
from ..domain.gafaelfawr import GafaelfawrUserInfo, UserGroup
from ..domain.kubernetes import PodPhase
from ..domain.rspimage import RSPImage

__all__ = [
    "CommonLabOptions",
    "ImageClass",
    "LabOptions",
    "LabRequestOptions",
    "LabResources",
    "LabSize",
    "LabSpecification",
    "LabState",
    "LabStatus",
    "ResourceQuantity",
    "UserInfo",
]


class LabSize(StrEnum):
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
    """Possible states the user's lab may be in.

    This is not directly equivalent to pod phases. It is instead intended to
    capture the status of the lab from an infrastructure standpoint,
    reflecting the current intent of the controller. Most notably, labs that
    have stopped running for any reason (failure or success) use the
    terminated status. The failed status is reserved for failed Kubernetes
    operations or missing or invalid Kubernetes objects.
    """

    PENDING = "pending"
    RUNNING = "running"
    TERMINATING = "terminating"
    TERMINATED = "terminated"
    FAILED = "failed"

    @classmethod
    def from_phase(cls, phase: PodPhase) -> LabStatus:
        """Convert a Kubernetes pod phase to a lab status.

        Be aware that it is not possible to detect Kubernetes pods that are in
        the process of being terminated by looking only at the phase
        (``Terminating`` is not a pod phase).

        Parameters
        ----------
        phase
            Kubernetes pod phase, from the ``Pod`` object.

        Returns
        -------
        LabStatus
            Corresponding lab status.
        """
        match phase:
            case PodPhase.PENDING:
                return cls.PENDING
            case PodPhase.RUNNING:
                return cls.RUNNING
            case PodPhase.SUCCEEDED | PodPhase.FAILED:
                return cls.TERMINATED
            case PodPhase.UNKNOWN:
                return cls.FAILED


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


class CommonLabOptions(BaseModel):
    """Options shared by both the input and output model for lab options."""

    size: Annotated[
        LabSize,
        Field(
            title="Image size",
            description=(
                "Size of image, chosen from sizes specified in the controller"
                " configuration"
            ),
            examples=[LabSize.MEDIUM],
        ),
    ]

    enable_debug: Annotated[
        bool,
        Field(
            title="Enable debugging in spawned Lab",
            description=(
                "If true, set the ``DEBUG`` environment variable when"
                " spawning the lab, which enables additional debug logging"
            ),
            examples=[True],
        ),
    ] = False

    reset_user_env: Annotated[
        bool,
        Field(
            title="Move aside user environment",
            description=(
                "If true, set the ``RESET_USER_ENV`` environment variable when"
                " spawning the lab, which tells the lab to move aside the user"
                " environment directories (``.cache``, ``.conda``,"
                " ``.jupyter``, ``.local``) and files (``.user_setups``)."
                " This can be used to recover from user configuration errors"
                " that break lab startup."
            ),
            examples=[True],
        ),
    ] = False


class LabOptions(CommonLabOptions):
    """Options for the lab, specified at creation time.

    This model represents the configuration information about a running lab
    returned by a JSON API query. It shares many attributes in common with the
    input model, `LabRequestOptions`, but reduces the requested image to a
    Docker image reference and doesn't support the complex validation required
    by `LabRequestOptions`.
    """

    image: Annotated[
        str,
        Field(
            title="Lab image",
            description="Docker reference to image used by the lab",
            examples=[
                "lighthouse.ceres/library/sketchbook:w_2023_07@sha256:abcd"
            ],
        ),
    ]


class LabRequestOptions(CommonLabOptions):
    """User-provided lab configuration options.

    This model represents the form submission to the spawner HTML form
    presented to the user by JupyterHub.

    All values to this model can instead be given as lists of length one, with
    boolean values converted to the strings ``true`` or ``false``. This is the
    form in which the values are received by the JupyterHub spawner form
    processing code, and allows JupyterHub to pass its form submission
    directly to the lab controller without modifications.
    """

    # Defining these fields using Annotated causes Sphinx documentation
    # generation to blow up with weird error messages.

    image_list: str | None = Field(
        None,
        title="Image from selection radio button",
        description=(
            "Selected image from the radio button part of the image menu,"
            f" or the special value ``{DROPDOWN_SENTINEL_VALUE}``. If this"
            " is set, to a value other than"
            f" ``{DROPDOWN_SENTINEL_VALUE}``, ``image_dropdown`` should"
            " not be set."
        ),
        examples=["lighthouse.ceres/library/sketchbook:w_2023_07@sha256:abcd"],
    )

    image_dropdown: str | None = Field(
        None,
        title="Image from dropdown list",
        description=(
            "Selected image from the dropdown part of the image menu. If"
            " this is set, ``image_list`` should be omitted or set to"
            f" ``{DROPDOWN_SENTINEL_VALUE}``."
        ),
        examples=["lighthouse.ceres/library/sketchbook:w_2022_40"],
    )

    image_class: ImageClass | None = Field(
        None,
        title="Class of image to spawn",
        description=(
            "Spawn a class of image determined by the lab controller. Not"
            " used by the user form, but may be used by bots creating"
            " labs. Only one of ``image_class`` or ``image_tag`` may be"
            " given, and neither ``image_list`` nor ``image_dropdown``"
            " should be set when using these options."
        ),
        examples=[ImageClass.RECOMMENDED],
    )

    image_tag: str | None = Field(
        None,
        title="Tag of image to spawn",
        description=(
            "Spawn the image with the given tag. Not used by the user"
            " form, but may be used by bots creating labs. Only one of"
            " ``image_class`` or ``image_tag`` may be given, and neither"
            " ``image_list`` nor ``image_dropdown`` should be set when"
            " using these options."
        ),
        examples=["w_2023_07"],
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

    @model_validator(mode="before")
    @classmethod
    def _validate_lists(
        cls, data: dict[str, Any] | Self
    ) -> dict[str, Any] | Self:
        """Convert from lists of length 1 to values.

        JupyterHub passes the value of the input form directly to the lab
        controller via this model. This means that each submitted field is a
        list, due to implementation details of JupyterHub, but in each case
        the list must have exactly one element and we don't want the list
        wrapper. Also accept values without the list wrapping for direct calls
        to the lab controller via the same API.
        """
        if not isinstance(data, dict):
            return data
        new_data = {}
        for key, value in data.items():
            if value is None:
                continue
            if isinstance(value, list):
                if not value:
                    continue
                if len(value) != 1:
                    raise ValueError(f"Too many values for {key}")
                new_data[key] = value[0]
            else:
                new_data[key] = value
        return new_data

    @model_validator(mode="after")
    def _validate_one_image(self) -> Self:
        """Ensure that the image is only specified in one way."""
        if self.image_list == DROPDOWN_SENTINEL_VALUE:
            self.image_list = None

        # image_dropdown will have a spurious value if image_list is set,
        # due to the form design, so in that case use image_list. (Unless
        # it has the sentinel value, but that's handled above.)
        if self.image_list:
            self.image_dropdown = None

        # See which image attributes are set.
        values_set = {
            attr
            for attr in (
                "image_list",
                "image_dropdown",
                "image_class",
                "image_tag",
            )
            if getattr(self, attr, None)
        }

        # Check that exactly one of them is set.
        if len(values_set) < 1:
            raise ValueError("No image to spawn specified")
        if len(values_set) > 1:
            keys = ", ".join(sorted(values_set))
            raise ValueError(f"Image specified multiple ways ({keys})")
        return self

    @field_validator("enable_debug", "reset_user_env", mode="before")
    @classmethod
    def _validate_booleans(cls, v: bool | str) -> bool:  # noqa: FBT001
        """Convert boolean values from strings."""
        if isinstance(v, bool):
            return v
        elif v == "true":
            return True
        elif v == "false":
            return False
        else:
            raise ValueError(f"Invalid boolean value {v}")

    @field_validator("size", mode="before")
    @classmethod
    def _validate_size(cls, v: Any) -> Any:
        """Lab sizes may be title-cased, so convert them to lowercase."""
        if isinstance(v, LabSize):
            return v
        elif isinstance(v, str):
            return v.lower()
        else:
            return v


class LabSpecification(BaseModel):
    """Specification of lab to spawn, sent by the JupyterHub spawner.

    This model is used for the POST body of the
    :samp:`/spawner/v1/labs/{username}/create` route.
    """

    options: Annotated[
        LabRequestOptions,
        Field(
            title="User-chosen lab options",
            description="Represents the choices made on the spawner form",
        ),
    ]

    env: Annotated[
        dict[str, str],
        Field(
            title="Environment variables",
            description=(
                "Environment variables from JupyterHub. The variable"
                " ``JUPYTERHUB_SERVICE_PREFIX`` must be set."
            ),
        ),
    ]

    @field_validator("env")
    @classmethod
    def _validate_env(cls, v: dict[str, str]) -> dict[str, str]:
        """Ensure ``JUPYTERHUB_SERVICE_PREFIX`` is set."""
        if "JUPYTERHUB_SERVICE_PREFIX" not in v:
            raise ValueError("JUPYTERHUB_SERVICE_PREFIX must be set")
        return v


class UserInfo(BaseModel):
    """Metadata about the user who owns the lab."""

    username: Annotated[
        str,
        Field(
            title="Username",
            description="Username of the owner of this lab",
            examples=["ribbon"],
            pattern=USERNAME_REGEX,
        ),
    ]

    name: Annotated[
        str | None,
        Field(
            title="Display name for user",
            description=(
                "Preferred human-readable name for the user. May contain"
                " spaces, capital letters, and non-ASCII Unicode characters."
                " Should be the user's preferred representation of their name"
                " to other humans."
            ),
            examples=["Ribbon"],
        ),
    ] = None

    uid: Annotated[
        int,
        Field(
            title="Numeric UID",
            description=(
                "POSIX numeric UID for the user as a 32-bit unsigned integer"
            ),
            examples=[1104],
        ),
    ]

    gid: Annotated[
        int,
        Field(
            title="Numeric GID of primary group",
            description=(
                "POSIX numeric GID for user's primary group as a 32-bit"
                " unsigned integer"
            ),
            examples=[1104],
        ),
    ]

    groups: Annotated[
        list[UserGroup],
        Field(
            title="User's group memberships",
            description=(
                "All POSIX group memberships of the user with associated GIDs,"
                " used to set the user's supplemental groups"
            ),
        ),
    ] = []

    @classmethod
    def from_gafaelfawr(cls, user: GafaelfawrUserInfo) -> Self:
        """Convert Gafaelfawr's user metadata model to this model.

        Groups without GIDs will be ignored, since they cannot be used by the
        lab spawner to set supplemental groups and cannot be referenced in the
        lab :file:`/etc/group` file.

        Parameters
        ----------
        user
            Gafaelfawr user metadata.

        Returns
        -------
        UserInfo
            User information stored as part of the lab state.
        """
        return cls(
            username=user.username,
            name=user.name,
            uid=user.uid,
            gid=user.gid,
            groups=user.groups,
        )


class ResourceQuantity(BaseModel):
    """A Kubernetes resource request or limit."""

    cpu: Annotated[
        float,
        Field(
            title="CPU",
            description="Number of CPU cores",
            examples=[1.5],
        ),
    ]

    memory: Annotated[
        int,
        Field(
            title="Memory",
            description=(
                "Amount of memory in bytes. Also accepts strings with SI"
                " suffixes, which will be converted to bytes. Be sure to use"
                " the suffix with ``i`` to indicate powers of two (1024 rather"
                " than 1000) if that is desired."
            ),
            examples=[1073741824, "1Gi"],
        ),
        BeforeValidator(
            lambda v: memory_to_bytes(v) if isinstance(v, str) else v
        ),
    ]


class LabResources(BaseModel):
    """Resource requests and limits for a lab."""

    limits: Annotated[
        ResourceQuantity,
        Field(
            title="Maximum allowed resources",
            description=(
                "If the user's pod exceeds this CPU limit, it will be"
                " throttled. If it exceeds this memory limit, it will usually"
                " be killed with an out-of-memory error."
            ),
        ),
    ]

    requests: Annotated[
        ResourceQuantity,
        Field(
            title="Minimum requested resources",
            description=(
                "Guaranteed minimum resources available to the user's lab. If"
                " these resources are not available, the cluster will"
                " autoscale or the lab spawn will fail."
            ),
        ),
    ]

    def to_kubernetes(self) -> V1ResourceRequirements:
        """Convert to the Kubernetes object representation."""
        return V1ResourceRequirements(
            limits={
                "cpu": str(self.limits.cpu),
                "memory": str(self.limits.memory),
            },
            requests={
                "cpu": str(self.requests.cpu),
                "memory": str(self.requests.memory),
            },
        )


class LabState(BaseModel):
    """Current state of the user's lab.

    This model is returned by the :samp:`/spawner/v1/labs/{username}` and
    ``/spawner/v1/user-status`` routes.
    """

    user: Annotated[
        UserInfo,
        Field(
            title="Owner",
            description="Metadata for the user who owns the lab",
        ),
    ]

    options: Annotated[
        LabOptions,
        Field(
            title="Lab options",
            description="Options for the lab, specified when it was requested",
        ),
    ]

    status: Annotated[
        LabStatus,
        Field(
            title="Status of user lab",
            description=(
                "Current status of the user's lab. This is primarily based on"
                " the Kubernetes pod phase, but does not have a one-to-one"
                " correspondence. Labs may be in ``failed`` state for a"
                " variety of reasons regardless of the pod phase, and"
                " completed pods are shown as ``terminated``."
            ),
            examples=[LabStatus.RUNNING],
        ),
    ]

    internal_url: Annotated[
        str | None,
        Field(
            title="URL for user's lab",
            description=(
                "URL used by JupyterHub and its proxy to access the user's"
                " lab. This is a cluster-internal URL that will not be"
                " meaningful outside of the cluster."
            ),
            examples=["http://nublado-ribbon.nb-ribbon:8888"],
        ),
    ] = None

    resources: Annotated[
        LabResources,
        Field(
            title="Lab resource limits and requests",
            description="Resource limits and requests for the lab pod",
        ),
    ]

    quota: Annotated[
        ResourceQuantity | None,
        Field(
            title="Quota for all user resources",
            description=(
                "Namespace quota for the user. Unlike `resources`, these"
                " limits are applied to the entire namespace, including worker"
                " pods spawned by the user."
            ),
        ),
    ] = None

    @classmethod
    def from_request(
        cls,
        *,
        user: GafaelfawrUserInfo,
        spec: LabSpecification,
        image: RSPImage,
        resources: LabResources,
    ) -> Self:
        """Create state for a new lab that is about to be spawned.

        Parameters
        ----------
        user
            Owner of the lab.
        spec
            Lab specification from the request.
        image
            Resolved image that the lab will run.
        resources
            Resource limits and requests for the lab.

        Returns
        -------
        LabState
            New user lab state representing a lab that's about to be spawned.
        """
        quota = None
        if user.quota and user.quota.notebook:
            quota = ResourceQuantity(
                cpu=user.quota.notebook.cpu,
                memory=int(user.quota.notebook.memory * 1024 * 1024 * 1024),
            )
        return cls(
            user=UserInfo.from_gafaelfawr(user),
            options=LabOptions(
                image=image.reference_with_digest,
                size=spec.options.size,
                enable_debug=spec.options.enable_debug,
                reset_user_env=spec.options.reset_user_env,
            ),
            status=LabStatus.PENDING,
            resources=resources,
            quota=quota,
        )

    @property
    def is_running(self) -> bool:
        """Whether the lab is currently running."""
        return self.status not in (LabStatus.TERMINATED, LabStatus.FAILED)
