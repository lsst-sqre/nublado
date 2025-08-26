"""API-visible model for fsadmin."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field
from safir.pydantic import UtcDatetime

from ..domain.kubernetes import PodPhase

__all__ = ["FSAdminCommand", "FSAdminStatus"]


class FSAdminCommand(BaseModel):
    """Command to start the file system admin pod."""

    start: Annotated[
        Literal[True], Field(title="must be True to start fileserver")
    ]


class FSAdminStatus(BaseModel):
    """Status for a running file system admin pod."""

    phase: Annotated[
        PodPhase,
        Field(title="Phase fsadmin pod is in (should be PodPhase.RUNNING)"),
    ]

    start_time: Annotated[
        UtcDatetime,
        Field(
            title="When the fsadmin pod was started",
            examples=["2025-08-25T16:57:38.825103+00:00"],
        ),
    ]
