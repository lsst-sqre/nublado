"""Exceptions for the LabRunner startup service."""

import errno
import os
import subprocess
from collections.abc import Iterable
from enum import IntEnum
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
        self, args: Iterable[str], exc: subprocess.CalledProcessError
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
        self, args: Iterable[str], exc: subprocess.TimeoutExpired
    ) -> None:
        args_str = join(args)
        msg = f"'{args_str}' timed out after {exc.timeout}s"
        super().__init__(msg)
        self.stdout = exc.stdout
        self.stderr = exc.stderr


# These are new errors, which are structured like OSError, but aren't.
# OSError's errno tops out at 106 as of Python 3.12 on x64 Linux, so we will
# start at 200 to give that some expansion room.


class RSPErrorCode(IntEnum):
    """New Error codes for RSP Startup."""

    # These values are written into env.json as ABNORMAL_STARTUP_ERRNO and
    # read by rsp-jupyter-extensions, which is not part of this codebase and
    # is loaded (and does error reporting) within JupyterLab startup.
    # Only ever append: renumbering an existing code will make an
    # older Lab image report the wrong error.
    EBADENV = 200
    EUNKNOWN = 201
    ENOWRITEABLESERVERROOT = 202


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
    RSPErrorCode.ENOWRITEABLESERVERROOT.value: {
        "errorcode": "ENOWRITEABLESERVERROOT",  # Nowhere to start server
        "strerror": "No writeable directory for the Lab server root",
    },
}


class RSPStartupError(OSError):
    """RSPStartupError is a subclass of OSError that is designed to be
    more portable than the standard OSError, since we are throwing it
    to a client that could, potentially, be running on a different
    architecture or OS, and whose numeric error codes might therefore
    not match (e.g. ``EDQUOT`` is 69 under MacOS aarch64, but 122 for
    Linux x64).

    This also gives us the opportunity to set the ``filename`` parameter
    to, for instance, indicate a missing environment variable.

    Notes
    -----
    Unlike `OSError`, the arguments are POSIX-only, and there is no
    ``winerror`` among them::

        RSPStartupError(errno, strerror, filename, filename2)

    All of them are optional.  ``errno`` may be either a standard `errno`
    value or one of ours from `RSPErrorCode`; anything else, including no
    arguments at all, is reported as ``EUNKNOWN``.  Omit ``strerror``, or pass
    `None`, to get the default message for that error number.

    The RSP does not run on Windows, so ``winerror`` is always `None`.  Do not
    reintroduce it as an argument: `OSError` would take it as the fourth
    positional argument, which is where we want ``filename2``.
    """

    # Additional errors we're defining, not present in
    # OSError
    #
    # For Python 3.12 on x64 Linux, at least, errno.errorcode has a greatest
    # value of 106.  So we're going to start at 200 for our custom errors.

    def __init__(self, *args: Any) -> None:
        # OSError takes a lone argument as the message rather than as the
        # error number, and it takes its fourth positional argument as
        # winerror.  So rather than forwarding our arguments, normalize them
        # and hand the superclass a full positional argument list with None in
        # the winerror slot.  That way OSError itself parses out filename and
        # filename2, and we do not have to reassign them afterwards.
        errnum = (
            int(args[0])
            if args and isinstance(args[0], int)
            else RSPErrorCode.EUNKNOWN.value
        )
        if errnum not in _rsp_errors and errnum not in errno.errorcode:
            # It's not one of ours, and it's not standard.
            # That makes it unknown.
            errnum = RSPErrorCode.EUNKNOWN.value
        strerror = args[1] if len(args) > 1 else None
        filename = args[2] if len(args) > 2 else None
        filename2 = args[3] if len(args) > 3 else None
        super().__init__(
            errnum,
            strerror or self._default_strerror(errnum),
            filename,
            None,  # winerror; see the class docstring.
            filename2,
        )
        # We name the code rather than its value, in case we renumber.  A
        # standard errno keeps its own name, and everything else is one of
        # ours, because we mapped the unrecognized cases to EUNKNOWN above.
        self.errorcode = errno.errorcode.get(errnum) or str(
            _rsp_errors[errnum]["errorcode"]
        )
        # OSError does not define this at all on POSIX.  Set it so that
        # reading it is safe, and so that it can never carry a real value.
        self.winerror = None

    @staticmethod
    def _default_strerror(errnum: int) -> str:
        """Return the stock message for an error number, ours or standard."""
        rsp_e = _rsp_errors.get(errnum)
        if rsp_e:
            return str(rsp_e["strerror"])
        return os.strerror(errnum) or f"Unknown error {errnum}"

    @classmethod
    def from_os_error(cls, exc: OSError) -> Self:
        """Create one of these from an underlying OSError exception."""
        # filename2 will probably never be set in the RSP startup use case.
        # Deliberately no winerror: see the class docstring.
        errnum = exc.errno or RSPErrorCode.EUNKNOWN.value
        strerror = (
            exc.strerror or os.strerror(errnum) or f"Unknown error {errnum}"
        )
        return cls(errnum, strerror, exc.filename, exc.filename2)
