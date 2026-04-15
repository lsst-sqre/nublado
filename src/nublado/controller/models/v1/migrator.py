"""API-visible model for migrator."""

import datetime
from typing import Annotated

from pydantic import BaseModel, Field, field_validator

from ...exceptions import (
    CopyError,
    CopyPermissionError,
    NoSourceUserDirectoryError,
    NoTargetUserDirectoryError,
)

__all__ = ["MigratorCommand", "MigratorStatus"]


class MigratorCommand(BaseModel):
    """Command to start the file system admin pod."""

    old_user: Annotated[str, Field(title="Source user to copy from")]
    new_user: Annotated[str, Field(title="Target user to copy to")]


class MigratorStatus(BaseModel):
    """Status for a migrator pod."""

    old_user: Annotated[str, Field(title="Source username to copy from")]

    new_user: Annotated[str, Field(title="Target username to copy to")]

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

    running: Annotated[
        bool, Field(title="Whether migrator pod is running")
    ] = True

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

    def raise_for_status(self) -> None:
        """If the MigratorStatus indicates an error, raise the
        corresponding exception.

        Return
        -------
        MigratorStatus
            The input object, if it did not raise an exception

        Raises
        ------
        controller.exceptions.NoSourceUserDirectoryError
            Raised if the source user's directory could not be found.
        controller.exceptions.NoTargetUserDirectoryError
            Raised if the target user's directory could not be found.
        controller.exceptions.CopyError
            Raised if there was a problem during file copy.
        controller.exceptions.CopyPermissionError
            Raised if there was a problem changing file ownership after copy.
        RuntimeError
            Raised if other constraints were violated (e.g. running but has
            exit code).
        """
        self._check_constraints()
        match self.exit_code:
            case None:
                pass
            case 0:
                pass
            case 4:
                raise NoSourceUserDirectoryError(self.old_user)
            case 5:
                raise NoTargetUserDirectoryError(self.new_user)
            case 6:
                raise CopyError(f"{self.old_user} -> {self.new_user}")
            case 7:
                raise CopyPermissionError(
                    f"{self.old_user} -> {self.new_user}"
                )
            case _:
                raise RuntimeError(
                    f"Migrator process exit code {self.exit_code}"
                    " is uninterpretable."
                )

    def _check_constraints(self) -> None:
        """Check for various impossible combinations of fields."""
        if self.running is True and self.exit_code is not None:
            raise RuntimeError(
                f"{self.old_user} -> {self.new_user} is running, but"
                f" has exit code {self.exit_code}"
            )
        if self.running is True and self.end_time is not None:
            raise RuntimeError(
                f"{self.old_user} -> {self.new_user} is running, but"
                f" has end_time {self.end_time}"
            )
        if self.running is False and self.exit_code is None:
            raise RuntimeError(
                f"{self.old_user} -> {self.new_user} is not running, but"
                " has no exit code"
            )
        if self.running is False and self.end_time is None:
            raise RuntimeError(
                f"{self.old_user} -> {self.new_user} is not running, but"
                " has no end time."
            )
        if self.end_time is not None:
            et = datetime.datetime.fromisoformat(self.end_time)
            st = datetime.datetime.fromisoformat(self.start_time)
            elapsed = (et - st).total_seconds()
            if elapsed < 0:
                raise RuntimeError(
                    f"Start time {self.start_time} is after end time"
                    f" {self.end_time}"
                )
