"""API-visible model for fsadmin."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

__all__ = ["FSAdminCommand"]


class FSAdminCommand(BaseModel):
    """Command to start the file system admin pod."""

    start: Annotated[
        Literal[True], Field(title="must be True to start fileserver")
    ]
