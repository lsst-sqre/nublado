"""Migrate files: given an old home directory a new home directory, copy all
the files from the old username into a datestamped subdirectory of the new
directory, setting ownership to the new user.

This is a slow operation; we expect to be running this in its own privileged
container.  Thus communication with the Nublado controller, which will
schedule this work, will be done via container exit code and Kubernetes status.
"""

import datetime
import os
import shutil
from pathlib import Path
from typing import Self

import structlog
from safir.logging import LogLevel, configure_logging

from ._constants import APP_NAME
from ._exceptions import (
    BaseMigratorError,
    CopyError,
    CopyPermissionError,
    NoSourceUserDirectoryError,
    NoTargetUserDirectoryError,
    errorexit,
)

__all__ = ["Migrator"]


class Migrator:
    """Convenience container for file migration."""

    def __init__(
        self,
        old_user: str,
        new_user: str,
        old_homedir: str | None = None,
        new_homedir: str | None = None,
        *,
        debug: bool = False,
    ) -> None:
        self._oldu = old_user
        self._newu = new_user
        if not old_homedir:
            old_homedir = f"/home/{old_user}"
        if not new_homedir:
            new_homedir = f"/home/{new_user}"
        self._old = old_homedir
        self._new = new_homedir
        self._debug = debug
        _level = LogLevel.DEBUG if debug else LogLevel.INFO
        configure_logging(name=APP_NAME, log_level=_level)
        self._logger = structlog.getLogger(APP_NAME)
        self._logger.debug("Migrator logging started")
        self._logger.debug(f"Resolving paths for {self._old} and {self._new}")
        self._determine_paths()

    def go(self) -> None:
        self._copy_files()
        self._chown_files()

    @classmethod
    def from_env(cls) -> Self:
        try:
            _old = os.environ.get("NUBLADO_OLD_USER")
            if not _old:
                raise NoSourceUserDirectoryError("Unknown old user")
            _new = os.environ.get("NUBLADO_NEW_USER")
            if not _new:
                raise NoTargetUserDirectoryError("Unknown new user")
        except BaseMigratorError as exc:
            errorexit(exc)
        _old_p = os.environ.get("NUBLADO_OLD_HOMEDIR")
        _new_p = os.environ.get("NUBLADO_NEW_HOMEDIR")
        _debug = bool(os.environ.get("DEBUG")) or bool(
            os.environ.get("NUBLADO_DEBUG")
        )
        return cls(
            old_user=_old,
            new_user=_new,
            old_homedir=_old_p,
            new_homedir=_new_p,
            debug=_debug,
        )

    def _determine_paths(self) -> None:
        try:
            self._src_p = Path(self._old)
            if not self._src_p.exists() or not self._src_p.is_dir():
                raise NoSourceUserDirectoryError(self._old)
            self._dest_p = Path(self._new)
            if not self._dest_p.exists() or not self._dest_p.is_dir():
                raise NoTargetUserDirectoryError(self._new)
            _stat = self._dest_p.stat()
            self._uid = _stat.st_uid
            self._gid = _stat.st_gid
        except BaseMigratorError as exc:
            errorexit(exc)
        self._logger.debug(f"Resolved paths for {self._old} and {self._new}")

    def _copy_files(self) -> None:
        stamp = datetime.datetime.now(tz=datetime.UTC).isoformat()
        self._dest = self._dest_p / f"migrated-{self._oldu}-{stamp}"
        self._logger.debug(f"Copying files: {self._old} -> {self._dest!s}")
        try:
            # This may take hours.  Check progress from the Nublado
            # controller.
            shutil.copytree(
                self._src_p,
                self._dest,
                symlinks=True,
                ignore_dangling_symlinks=True,
            )
        except Exception as exc:
            newexc = CopyError(repr(exc))
            errorexit(newexc)
        self._logger.debug(f"Copied files: {self._old} -> {self._dest!s}")

    def _chown_files(self) -> None:
        self._logger.debug(
            f"Changing {self._dest!s} ownership to {self._uid}/{self._gid}"
        )
        try:
            for dirpath, _, filenames in self._dest.walk(
                follow_symlinks=False
            ):
                shutil.chown(
                    dirpath,
                    user=self._uid,
                    group=self._gid,
                    follow_symlinks=False,
                )
                for fn in filenames:
                    shutil.chown(
                        (dirpath / fn), user=self._uid, group=self._gid
                    )
        except Exception as exc:
            newexc = CopyPermissionError(repr(exc))
            errorexit(newexc)
        self._logger.debug(
            f"Changed {self._dest!s} ownership to {self._uid}/{self._gid}"
        )
