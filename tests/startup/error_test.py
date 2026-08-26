"""Test custom exception generation."""

import errno
import os
from pathlib import Path

import pytest

from nublado.startup.exceptions import (
    RSPErrorCode,
    RSPStartupError,
    _rsp_errors,
)


def test_no_argument_error() -> None:
    """Check that no arguments gives generic Unknown Error."""
    err = RSPStartupError()
    assert err.errno == RSPErrorCode.EUNKNOWN
    assert err.errorcode == _rsp_errors[err.errno]["errorcode"]
    assert err.strerror == _rsp_errors[err.errno]["strerror"]


def test_unrecognized_error() -> None:
    """Check that an error number we do not know becomes EUNKNOWN."""
    err = RSPStartupError(9999)
    assert err.errno == RSPErrorCode.EUNKNOWN
    assert err.errorcode == "EUNKNOWN"
    assert err.strerror == _rsp_errors[RSPErrorCode.EUNKNOWN]["strerror"]


def test_standard_errno_gets_default_message() -> None:
    """A standard errno passed on its own still gets its stock message.

    The error message reaches the user through str() of the exception, so a
    missing strerror would render as "[Errno 2] None".
    """
    err = RSPStartupError(errno.ENOENT)
    assert err.errno == errno.ENOENT
    assert err.errorcode == "ENOENT"
    assert err.strerror == os.strerror(errno.ENOENT)
    assert "None" not in str(err)


def test_one_argument_error() -> None:
    """Check that one argument gives correct error and default text."""
    err = RSPStartupError(RSPErrorCode.ENOWRITEABLESERVERROOT)
    assert err.errno == RSPErrorCode.ENOWRITEABLESERVERROOT
    assert err.errorcode == _rsp_errors[err.errno]["errorcode"]
    assert err.strerror == _rsp_errors[err.errno]["strerror"]


def test_two_argument_error() -> None:
    """Check that two arguments gives correct error and submitted text."""
    err = RSPStartupError(RSPErrorCode.EBADENV, "USER")
    assert err.errno == RSPErrorCode.EBADENV
    assert err.errorcode == _rsp_errors[err.errno]["errorcode"]
    assert err.strerror == "USER"


def test_three_argument_error() -> None:
    """Check that three arguments also sets filename attribute."""
    err = RSPStartupError(
        RSPErrorCode.EBADENV, "WRONGFILE", "/usr/local/share/foo"
    )
    assert err.errno == RSPErrorCode.EBADENV
    assert err.errorcode == _rsp_errors[err.errno]["errorcode"]
    assert err.strerror == "WRONGFILE"
    assert err.filename == "/usr/local/share/foo"


def test_four_argument_error() -> None:
    """Check that four arguments also sets filename2 attribute."""
    err = RSPStartupError(
        RSPErrorCode.EBADENV,
        "WRONGFILE",
        "/usr/local/share/foo",
        "/usr/local/share/bar",
    )
    assert err.errno == RSPErrorCode.EBADENV
    assert err.errorcode == _rsp_errors[err.errno]["errorcode"]
    assert err.strerror == "WRONGFILE"
    assert err.filename == "/usr/local/share/foo"
    assert err.filename2 == "/usr/local/share/bar"


def test_from_os_error() -> None:
    """Check that a real OSError converts to the equivalent RSP error."""
    with pytest.raises(FileNotFoundError) as excinfo:
        Path("/this/path/should/not/exist").read_text()
    err = RSPStartupError.from_os_error(excinfo.value)
    assert err.errno == errno.ENOENT
    assert err.errorcode == "ENOENT"
    assert err.strerror == os.strerror(errno.ENOENT)
    assert err.filename == "/this/path/should/not/exist"


def test_from_os_error_keeps_filename2() -> None:
    """filename2 must survive the round trip.

    It used to be overwritten by the winerror argument that from_os_error
    passed in the filename2 position.
    """
    # filename2 is not positional on POSIX, so set it directly.
    src = OSError(errno.EXDEV, "Invalid cross-device link", "/from")
    src.filename2 = "/to"
    err = RSPStartupError.from_os_error(src)
    assert err.filename == "/from"
    assert err.filename2 == "/to"


def test_no_winerror() -> None:
    """The RSP does not run on Windows, so winerror never has a value."""
    errs = [
        RSPStartupError(),
        RSPStartupError(RSPErrorCode.EBADENV),
        RSPStartupError(errno.ENOENT, "missing", "/f1", "/f2"),
        RSPStartupError.from_os_error(OSError(errno.EACCES, "denied", "/f1")),
    ]
    for err in errs:
        assert err.winerror is None
