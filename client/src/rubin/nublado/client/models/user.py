"""Data models for an authenticated user."""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = [
    "AuthenticatedUser",
    "User",
]


class User(BaseModel):
    """Configuration for the user the client produces."""

    username: str = Field(
        ...,
        title="Username",
    )

    uidnumber: int | None = Field(
        None,
        title="Numeric UID",
        description=(
            "If omitted, Gafaelfawr will assign a UID. (Gafaelfawr UID"
            " assignment requires Firestore be configured.)"
        ),
        examples=[60001],
    )

    gidnumber: int | None = Field(
        None,
        title="Primary GID",
        description=(
            "If omitted but a UID was specified, use a GID equal to the UID."
            " If both are omitted, Gafaelfawr will assign a UID and GID."
            " (Gafaelfawr UID and GID assignment requires Firestore and"
            " synthetic user private groups to be configured.)"
        ),
        examples=[60001],
    )


class AuthenticatedUser(User):
    """Represents an authenticated user with a token."""

    scopes: list[str] = Field(
        ...,
        title="Token scopes",
        examples=[["exec:notebook", "read:tap", "exec:portal"]],
    )

    token: str = Field(
        ...,
        title="Authentication token for user",
        examples=["gt-1PhgAeB-9Fsa-N1NhuTu_w.oRvMvAQp1bWfx8KCJKNohg"],
    )
