"""Exceptions for the LabRunner startup service."""

from __future__ import annotations

import errno
import os
import subprocess
from collections.abc import Iterable
from enum import Enum
from shlex import join
from typing import Any, Self

__all__ = [
    "CommandFailedError",
    "CommandTimedOutError",
    "RSPErrorCode",
    "RSPStartupError",
]


class CommandFailedError(Exception):
    """Execution of a command failed.

    Parameters
    ----------
    args
        Command (args[0]) and arguments to that command.
    exc
        Exception reporting the failure.

    Attributes
    ----------
    stdout
        Standard output from the failed command.
    stderr
        Standard error from the failed command.
    """

    def __init__(
        self,
        args: Iterable[str],
        exc: subprocess.CalledProcessError,
    ) -> None:
        args_str = join(args)
        msg = f"'{args_str}' failed with status {exc.returncode}"
        super().__init__(msg)
        self.stdout = exc.stdout
        self.stderr = exc.stderr


class CommandTimedOutError(Exception):
    """Execution of a command failed.

    Parameters
    ----------
    args
        Command (args[0]) and arguments to that command.
    exc
        Exception reporting the failure.

    Attributes
    ----------
    stdout
        Standard output from the failed command.
    stderr
        Standard error from the failed command.
    """

    def __init__(
        self,
        args: Iterable[str],
        exc: subprocess.TimeoutExpired,
    ) -> None:
        args_str = join(args)
        msg = f"'{args_str}' timed out after {exc.timeout}s"
        super().__init__(msg)
        self.stdout = exc.stdout
        self.stderr = exc.stderr


# These are new errors, which are structured like OSError, but aren't.
# OSError's errno tops out at 106 as of Python 3.12 on x64 Linux, so we will
# start at 200 to give that some expansion room.


class RSPErrorCode(Enum):
    """New Error codes for RSP Startup."""

    EBADENV = 200
    EUNKNOWN = 201


# Used internally to populate our RSPStartupErrors
_rsp_errors: dict[int, dict[str, str | int]] = {
    RSPErrorCode.EBADENV.value: {
        "errorcode": "EBADENV",  # Bad environment variable
        "strerror": "Missing environment variable",
    },
    RSPErrorCode.EUNKNOWN.value: {
        "errorcode": "EUNKNOWN",  # Unknown error
        "strerror": f"Unknown error {RSPErrorCode.EUNKNOWN.value}",
    },
}


class RSPStartupError(OSError):
    """RSPStartupError is a subclass of OSError that is designed to be
    more portable than the standard OSError, since we are throwing it
    to a client that could, potentially, be running on a different
    architecture or OS, and whose numeric error codes might therefore
    not match (e.g. `EDQUOT` is 69 under MacOS aarch64, but 122 for
    Linux x64).

    This also gives us the opportunity to set the `filename` parameter
    to, for instance, indicate a missing environment variable.
    """

    # Additional errors we're defining, not present in
    # OSError
    #
    # For Python 3.12 on x64 Linux, at least, errno.errorcode has a greatest
    # value of 106.  So we're going to start at 200 for our custom errors.

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        errnum = self.errno
        # See if it's one of our custom errors or unknown.
        if errnum is None:  # Just to keep mypy happy; can't happen.
            errnum = RSPErrorCode.EUNKNOWN.value
        vals = [x.value for x in RSPErrorCode]
        ec = errno.errorcode.get(errnum)
        if ec:
            self.errorcode = ec
            return
        if errnum not in vals:
            # It's not one of ours, and it's not standard.
            # That makes it unknown.
            # We say 201 the fancy way, in case we ever need to renumber.
            errnum = RSPErrorCode.EUNKNOWN.value
            self.errno = errnum
        errnum = self.errno  # Maybe we reset it to EUNKNOWN
        if errnum is None:  # Just to keep mypy happy; can't happen.
            errnum = RSPErrorCode.EUNKNOWN.value
        # We know this won't be a KeyError
        rsp_e = _rsp_errors[errnum]
        if len(args) > 1:
            strerror = args[1]
        self.strerror = strerror or str(rsp_e["strerror"])
        self.errorcode = str(rsp_e["errorcode"])
        if len(args) > 2:
            self.filename = args[2]
        # Assume winerror doesn't exist--if we're ever running on
        # Windows, we need to revisit.
        if len(args) > 3:
            self.filename2 = args[3]

    @classmethod
    def from_os_error(cls, exc: OSError) -> Self:
        """Create one of these from an underlying OSError exception."""
        # filename2 will probably never be set in the RSP startup use case.
        errnum = exc.errno or RSPErrorCode.EUNKNOWN.value
        strerror = (
            exc.strerror or os.strerror(errnum) or f"Unknown error {errnum}"
        )
        winerror = ""  # Change if we ever need windows support
        return cls(errnum, strerror, exc.filename, winerror, exc.filename2)
