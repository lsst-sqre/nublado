"""Models for talking to Gafaelfawr.

Ideally, these should use the same models Gafaelfawr itself uses. Until that's
possible via a PyPI library, these models are largely copied from Gafaelfawr.
"""

from __future__ import annotations

import json
from typing import Annotated

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
    """Gafaelfawr's representation of a single group."""

    name: Annotated[
        str,
        Field(
            examples=["ferrymen"],
            title="Group to which lab user belongs",
            description="Should follow Unix naming conventions",
            pattern=GROUPNAME_REGEX,
        ),
    ]

    id: Annotated[
        int,
        Field(
            examples=[2023],
            title="Numeric GID of the group (POSIX)",
            description="32-bit unsigned integer",
        ),
    ]


class NotebookQuota(BaseModel):
    """Notebook Aspect quota information for a user."""

    cpu: Annotated[float, Field(title="CPU equivalents", examples=[4.0])]

    memory: Annotated[
        float, Field(title="Maximum memory use (GiB)", examples=[16.0])
    ]

    @property
    def memory_bytes(self) -> int:
        """Maximum memory use in bytes."""
        return int(self.memory * 1024 * 1024 * 1024)


class UserQuota(BaseModel):
    """Quota information for a user."""

    api: Annotated[
        dict[str, int],
        Field(
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
        ),
    ] = {}

    notebook: Annotated[
        NotebookQuota | None, Field(title="Notebook Aspect quotas")
    ] = None


class GafaelfawrUserInfo(BaseModel):
    """User metadata from Gafaelfawr."""

    username: Annotated[
        str,
        Field(
            examples=["ribbon"],
            title="Username for Lab user",
            pattern=USERNAME_REGEX,
        ),
    ]

    name: Annotated[
        str | None,
        Field(
            examples=["Ribbon"],
            title="Human-friendly display name for user",
            description=(
                "May contain spaces, capital letters, and non-ASCII"
                " characters. Should be the user's preferred representation"
                " of their name to other humans."
            ),
        ),
    ] = None

    uid: Annotated[
        int,
        Field(
            examples=[1104],
            title="Numeric UID for user (POSIX)",
            description="32-bit unsigned integer",
        ),
    ]

    gid: Annotated[
        int,
        Field(
            examples=[1104],
            title="Numeric GID for user's primary group (POSIX)",
            description="32-bit unsigned integer",
        ),
    ]

    groups: Annotated[
        list[UserGroup], Field(title="User's group memberships")
    ] = []

    quota: Annotated[UserQuota | None, Field(title="User's quotas")] = None

    @property
    def supplemental_groups(self) -> list[int]:
        """Supplemental GIDs."""
        return [g.id for g in self.groups]

    def groups_json(self) -> str:
        """Group membership serialized to JSON."""
        return json.dumps([g.model_dump() for g in self.groups])


class GafaelfawrUser(GafaelfawrUserInfo):
    """User information from Gafaelfawr supplemented with the user's token.

    This model is used to pass the user information around internally,
    bundling the user's metadata with their notebook token.
    """

    token: Annotated[str, Field(title="Notebook token")]

    def to_headers(self) -> dict[str, str]:
        """Return the representation of this user as HTTP request headers.

        Used primarily by the test suite for constructing authenticated
        requests from a user.
        """
        return {
            "X-Auth-Request-Token": self.token,
            "X-Auth-Request-User": self.username,
        }
