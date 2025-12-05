"""API-visible models for user file servers."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field

__all__ = ["FileserverStatus"]


class FileserverStatus(BaseModel):
    """Status of a user's file server."""

    running: Annotated[
        bool, Field(title="Whether fileserver is running", examples=[True])
    ]
