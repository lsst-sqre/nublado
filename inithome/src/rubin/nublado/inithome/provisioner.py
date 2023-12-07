"""Provisioner for user home directories."""

import asyncio
import logging
import os
from pathlib import Path

MAX_ID = 2**32 - 1  # True for Linux, which is where we run inithome
# cf https://en.wikipedia.org/wiki/User_identifier
RESERVED_IDS = (MAX_ID, 0, 65535, 65534)


class Provisioner:
    """Object to oversee idempotent provisioning of home directories."""

    def __init__(self, uid: int, gid: int, homedir: Path) -> None:
        self._validate(uid, gid)
        self.uid = uid
        self.gid = gid
        self.homedir = homedir

    def _validate(self, uid: int, gid: int) -> None:
        for item in (uid, gid):
            if item in RESERVED_IDS:
                raise ValueError(
                    f"Will not provision for reserved UID/GID {item}"
                )
            if item < 0:
                raise ValueError("UID/GID must be positive")
            if item > MAX_ID:
                raise ValueError(f"UID/GID must be <= {MAX_ID}")

    async def provision(self) -> None:
        """Provision user home directory.

        This is the only public method.  Given an initialized
        object with UID, GID, and homedir path, if the path does not
        exist, create it and set it to mode 0700 for the path
        components created.

        If the path already exists, verify that it is a directory and owned
        by the right UID and GID; warn if mode is not correct, but don't treat
        that as a fatal error.  If ownership is not correct, then if and only
        if the directory is empty, warn and reset permissions appropriately.
        If it is not empty, raise a fatal error.
        """
        if self.homedir.exists():
            if not self.homedir.is_dir():
                raise RuntimeError(
                    f"{self.homedir} exists but is not a directory"
                )
            # Check ownership and permissions
            stat_results = self.homedir.stat()
            uid = stat_results.st_uid
            gid = stat_results.st_gid
            if uid != self.uid or gid != self.gid:
                is_empty = len(list(self.homedir.iterdir())) == 0
                msg = (
                    f"{self.homedir} is owned by {uid}:{gid}, not"
                    f"{self.uid}/{self.gid}"
                )
                if not is_empty:
                    raise RuntimeError(f"{msg} and is not empty")
                logger = logging.getLogger(__name__)
                logger.warning(f"{msg} but is empty; resetting ownership")
                os.chown(self.homedir, uid=self.uid, gid=self.gid)
            # We're masking st_mode because BSD and Linux disagree on file
            # type bit interpretation, and what we care about is rwx------
            if (stat_results.st_mode & 0o777) != 0o700:
                logger = logging.getLogger(__name__)
                logger.warning(
                    f"{self.homedir} has strange permissions "
                    f"{oct(stat_results.st_mode & 0o777)} rather than '0o700'"
                )
            return
        # We need to create the directory
        self.homedir.mkdir()
        self.homedir.chmod(mode=0o700)
        os.chown(self.homedir, uid=self.uid, gid=self.gid)


def main() -> None:
    """Entry point for provisioner.

    Environment variables `NUBLADO_UID` and `NUBLADO_HOME` must be set.
    """
    # All of these should fail if unset; KeyError is as good as anything.
    uid = int(os.environ["NUBLADO_UID"])
    gid = int(os.environ["NUBLADO_GID"])
    homedir = Path(os.environ["NUBLADO_HOME"])
    provisioner = Provisioner(uid=uid, gid=gid, homedir=homedir)
    asyncio.run(provisioner.provision())


if __name__ == "__main__":
    main()
