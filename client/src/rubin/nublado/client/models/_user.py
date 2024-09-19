"""Data model for an authenticated user."""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = [
    "User",
]


class User(BaseModel):
    """Configuration for the user the client operates as."""

    username: str = Field(
        ...,
        title="Username",
    )

    token: str = Field(
        ...,
        title="Authentication token for user",
        examples=["gt-1PhgAeB-9Fsa-N1NhuTu_w.oRvMvAQp1bWfx8KCJKNohg"],
    )
