"""Object representing files to be purged, and why."""

import datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated

from pydantic import Field
from safir.pydantic import CamelCaseModel


class FileClass(StrEnum):
    """Whether a file is large or small."""

    LARGE = "LARGE"
    SMALL = "SMALL"


class FileReason(StrEnum):
    """Whether a file is to be purged on access, creation, or modification
    time grounds.
    """

    ATIME = "ATIME"
    CTIME = "CTIME"
    MTIME = "MTIME"


class FileRecord(CamelCaseModel):
    """A file to be purged, and why."""

    path: Annotated[Path, Field(..., title="Path for file to purge.")]

    file_class: Annotated[
        FileClass, Field(..., title="Class of file to purge (large or small).")
    ]

    file_reason: Annotated[
        FileReason,
        Field(
            ...,
            title=(
                "Reason to purge file (access, creation, or modification"
                " time)."
            ),
        ),
    ]

    file_interval: Annotated[
        datetime.timedelta,
        Field(..., title="Time since the appropriate timestamp."),
    ]

    criterion_interval: Annotated[
        datetime.timedelta,
        Field(..., title="Interval at which file is marked for deletion."),
    ]

    def __str__(self) -> str:
        # The __str__ methods for this and the enclosing plan are designed
        # to produce reasonably-formatted reports.
        return (
            f"{self.path!s}: {self.file_reason.value}"
            f" {int(self.file_interval.total_seconds())}s >="
            f" {int(self.criterion_interval.total_seconds())}s"
        )


class Plan(CamelCaseModel):
    """List of files to be purged, and why."""

    directories: Annotated[
        list[Path], Field(..., title="Directories considered")
    ]
    files: Annotated[list[FileRecord], Field(..., title="Files to purge")]

    def __str__(self) -> str:
        if len(self.directories) == 0:
            return "No directories considered."
        rs = "Directories considered:\n"
        for sd in self.directories:
            rs += f"  {sd!s}\n"
        if len(self.files) == 0:
            rs += "No matching files found.\n"
        else:
            for sf in self.files:
                rs += f"  -> {sf.path!s}\n"
        return rs
