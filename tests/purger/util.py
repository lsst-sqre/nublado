"""Tools for testing."""

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from safir.pydantic._types import _validate_human_timedelta

from nublado.purger.models.plan import FileReason


def set_age(path: Path, whichtime: FileReason, h_age: str) -> None:
    v_age = _validate_human_timedelta(h_age)
    if isinstance(v_age, float):
        age = timedelta(seconds=v_age)
    elif isinstance(v_age, timedelta):
        age = v_age
    now = datetime.now(tz=UTC)
    then = int((now - age).timestamp())
    stat = path.stat()
    o_atime = stat.st_atime
    o_mtime = stat.st_mtime
    match whichtime:
        case FileReason.ATIME:
            os.utime(path, times=(then, o_mtime))
        case FileReason.CTIME:
            raise ValueError("Cannot set ctime")
        case FileReason.MTIME:
            os.utime(path, times=(o_atime, then))
        case _:
            raise ValueError(f"{then} is not a file access time category")
