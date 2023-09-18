"""Models for talking to Gafaelfawr.

Ideally, these should use the same models Gafaelfawr itself uses. Until that's
possible via a PyPI library, these models are largely copied from Gafaelfawr.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ...constants import GROUPNAME_REGEX, USERNAME_REGEX

__all__ = [
    "GafaelfawrUser",
    "GafaelfawrUserInfo",
    "NotebookQuota",
    "UserGroup",
    "UserQuota",
]


class UserGroup(BaseModel):
    name: str = Field(
        ...,
        examples=["ferrymen"],
        title="Group to which lab user belongs",
        description="Should follow Unix naming conventions",
        pattern=GROUPNAME_REGEX,
    )
    id: int | None = Field(
        None,
        examples=[2023],
        title="Numeric GID of the group (POSIX)",
        description="32-bit unsigned integer",
    )


class NotebookQuota(BaseModel):
    """Notebook Aspect quota information for a user."""

    cpu: float = Field(..., title="CPU equivalents", examples=[4.0])

    memory: float = Field(
        ..., title="Maximum memory use (GiB)", examples=[16.0]
    )


class UserQuota(BaseModel):
    """Quota information for a user."""

    api: dict[str, int] = Field(
        {},
        title="API quotas",
        description=(
            "Mapping of service names to allowed requests per 15 minutes."
        ),
        examples=[
            {
                "datalinker": 500,
                "hips": 2000,
                "tap": 500,
                "vo-cutouts": 100,
            }
        ],
    )

    notebook: NotebookQuota | None = Field(
        None, title="Notebook Aspect quotas"
    )


class GafaelfawrUserInfo(BaseModel):
    """User metadata from Gafaelfawr."""

    username: str = Field(
        ...,
        examples=["ribbon"],
        title="Username for Lab user",
        pattern=USERNAME_REGEX,
    )
    name: str = Field(
        ...,
        examples=["Ribbon"],
        title="Human-friendly display name for user",
        description=(
            "May contain spaces, capital letters, and non-ASCII characters."
            " Should be the user's preferred representation of their name to"
            " other humans."
        ),
    )
    uid: int = Field(
        ...,
        examples=[1104],
        title="Numeric UID for user (POSIX)",
        description="32-bit unsigned integer",
    )
    gid: int = Field(
        ...,
        examples=[1104],
        title="Numeric GID for user's primary group (POSIX)",
        description="32-bit unsigned integer",
    )
    groups: list[UserGroup] = Field([], title="User's group memberships")
    quota: UserQuota | None = Field(None, title="User's quotas")


class GafaelfawrUser(GafaelfawrUserInfo):
    """User information from Gafaelfawr supplemented with the user's token.

    This model is used to pass the user information around internally,
    bundling the user's metadata with their notebook token.
    """

    token: str = Field(..., title="Notebook token")
