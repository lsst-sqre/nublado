"""Top-level request models for the Nublado controller."""

from __future__ import annotations

from pydantic import BaseModel, Field
from safir.metadata import Metadata

__all__ = ["Index"]


class Index(BaseModel):
    """Metadata returned by the external root URL of the application."""

    metadata: Metadata = Field(..., title="Package metadata")
