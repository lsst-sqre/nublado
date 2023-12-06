"""Provisioner for user home directories."""

import asyncio
import logging
from os import chown, environ, getenv, umask
from pathlib import Path

MAX_ID = 2**32 - 1  # True for Linux, which is where we run inithome


class Provisioner:
    """Object to oversee idempotent provisioning of home directories."""

    def __init__(self, uid: int, gid: int, homedir: Path) -> None:
        self._validate(uid, gid)
        self.uid = uid
        self.gid = gid
        self.homedir = homedir

    def _validate(self, uid: int, gid: int) -> None:
        for item in (uid, gid):
            if item == 0:
                raise ValueError("Will not provision for UID/GID 0")
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
        that as a fatal error.
        """
        if self.homedir.exists():
            if not self.homedir.is_dir():
                raise RuntimeError(
                    f"{self.homedir} exists but is not a directory"
                )
            # Check ownership and permissions
            stat_results = self.homedir.stat()
            if stat_results.st_uid != self.uid:
                raise RuntimeError(
                    f"{self.homedir} is owned by {stat_results.st_uid}, not "
                    f"{self.uid}"
                )
            if stat_results.st_gid != self.gid:
                raise RuntimeError(
                    f"{self.homedir} is owned by group "
                    f"{stat_results.st_gid}, not {self.gid}"
                )
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
        # Set umask so intermediate paths are created mode 0o700 as well
        umask(0o077)
        # Find out how many layers of directory we need to create, for the
        # chown.
        first_created = self.homedir
        while True:
            if first_created.parent.is_dir() or first_created == Path("/"):
                break
            first_created = first_created.parent
        # Create the homedir (and path leading down to it if needed)
        self.homedir.mkdir(parents=True)
        # Climb the path, chown'ing until we get to a layer that previously
        # existed.  (Neither os.chown() nor shutil.chown() implements "-r")
        current_dir = self.homedir
        while True:
            chown(current_dir, uid=self.uid, gid=self.gid)
            if current_dir == first_created:
                break
            current_dir = current_dir.parent


def main() -> None:
    """Entry point for provisioner.

    Environment variables `NUBLADO_UID` and `NUBLADO_HOME` must be set.
    if NUBLADO_GID is unset it will get set to NUBLADO_UID.
    """
    uid = int(environ["NUBLADO_UID"])  # Fail if unset
    gid = int(getenv("NUBLADO_GID", uid))  # Default to UID
    homedir = Path(environ["NUBLADO_HOME"])  # Fail if unset
    provisioner = Provisioner(uid=uid, gid=gid, homedir=homedir)
    asyncio.run(provisioner.provision())


if __name__ == "__main__":
    main()
