"""Test custom exception generation."""

import errno
from pathlib import Path

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
    try:
        Path("/this/path/should/not/exist").read_text()
    except OSError as exc:
        err = RSPStartupError.from_os_error(exc)
    assert err.errno == errno.ENOENT
    assert err.errorcode == "ENOENT"
    assert err.filename == "/this/path/should/not/exist"
