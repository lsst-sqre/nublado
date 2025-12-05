"""Provisioner for user home directories."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import ClassVar

__all__ = ["InvalidHomeError", "Provisioner"]


class InvalidHomeError(Exception):
    """The home directory already exists but is not acceptable."""


class Provisioner:
    """Create the user's home directory if it doesn't exist.

    Parameters
    ----------
    home
        Path to the home directory to create.
    uid
        Numeric UID of the user.
    gid
        Numeric primary GID of the user.
    """

    _MAX_ID: ClassVar[int] = 2**32 - 2
    """Maximum UID or GID.

    Reject any UID or GID larger than this or less than zero, since the
    results may be unpredictable. Linux currently doesn't support UIDs or GIDs
    larger than this.
    """

    def __init__(self, home: Path, uid: int, gid: int) -> None:
        self._home = home
        self._uid = self._validate(uid)
        self._gid = self._validate(gid)
        self._logger = logging.getLogger(__name__)

    async def provision(self) -> None:
        """Create the user's home directory.

        If the home directory doesn't exist, create it and set it to mode
        0700. If it already exists, verify that it is a directory and owned by
        the correct UID and GID. If the permissions are incorrect and the
        directory is empty, fix the ownership; otherwise, warn but continue.
        Warn about unexpected modes, but don't treat them as fatal errors.

        Raises
        ------
        InvalidHomeError
            Raised if the path exists but is not a directory, or if it has the
            wrong ownership but is not empty.
        """
        if not self._home.exists():
            os.umask(0o077)
            self._home.mkdir()
            os.chown(self._home, self._uid, self._gid)
            return

        # The home directory already exists. Check that it appears as expected.
        if not self._home.is_dir():
            msg = f"{self._home} exists but is not a directory"
            raise InvalidHomeError(msg)

        # Check ownership and permissions.
        stat = self._home.stat()
        if stat.st_uid != self._uid or stat.st_gid != self._gid:
            msg = (
                f"{self._home} is owned by {stat.st_uid}:{stat.st_gid},"
                f" not {self._uid}:{self._gid}"
            )
            is_empty = len(list(self._home.iterdir())) == 0
            if not is_empty:
                raise InvalidHomeError(f"{msg} and is not empty")
            self._logger.warning(f"{msg} but is empty, resetting ownership")
            os.chown(self._home, self._uid, self._gid)

        # Check mode. We only care about the permission bits.
        mode = stat.st_mode & 0o777
        if mode != 0o700:
            msg = f"{self._home} has unexpected permissions: 0{mode:o} != 0700"
            self._logger.warning(msg)

    def _validate(self, ugid: int) -> int:
        """Validate that a UID or GID is within range.

        This intentionally does not reject a UID or GID of 0, although for a
        UID this would normally be questionable. Gafaelfawr should prevent
        unreasonable UIDs or GIDs upstream of Nublado, and there may be
        unanticipated situations where calling this code with a UID of 0 makes
        sense.

        Raises
        ------
        ValueError
            Raised if the provided UID or GID is out of range.
        """
        if ugid < 0:
            raise ValueError(f"UID or GID must be nonnegative, not {ugid}")
        if ugid > self._MAX_ID:
            msg = f"UID or GID out of range ({ugid} > {self._MAX_ID})"
            raise ValueError(msg)
        return ugid
