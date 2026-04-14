"""API-visible model for migrator."""

import datetime
from typing import Annotated

from pydantic import BaseModel, Field, field_validator

__all__ = ["MigratorCommand", "MigratorStatus"]


class MigratorCommand(BaseModel):
    """Command to start the file system admin pod."""

    new_user: Annotated[str, Field(title="Target user to copy to")]
    old_user: Annotated[str, Field(title="Source user to copy from")]


class MigratorStatus(BaseModel):
    """Status for a migrator pod."""

    start_time: Annotated[
        str,
        Field(
            title="When the migrator pod was started",
            examples=["2026-04-25T16:57:38.825103+00:00"],
        ),
    ] = datetime.datetime.now(tz=datetime.UTC).isoformat()

    end_time: Annotated[
        str | None,
        Field(
            title="When the migrator pod exited (if it has)",
            examples=["2026-04-25T16:59:38.825103+00:00"],
        ),
    ] = None

    exit_code: Annotated[
        int | None, Field(title="Exit code (if any) for migrator pod")
    ] = None

    @field_validator("start_time", "end_time", mode="before")
    @classmethod
    def _validate_start_time(cls, v: str | None) -> str | None:
        if v is None:
            return None
        try:
            _ = datetime.datetime.fromisoformat(v)
        except Exception:
            raise ValueError(f"{v} cannot be parsed as a datestamp") from None
        return v
