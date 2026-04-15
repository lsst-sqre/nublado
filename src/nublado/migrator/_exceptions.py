"""Exceptions for migrator."""

import sys
from typing import Never

__all__ = [
    "BaseMigratorError",
    "CopyError",
    "CopyPermissionError",
    "NoSourceUserDirectoryError",
    "NoTargetUserDirectoryError",
    "errorexit",
]


def errorexit(exc: BaseMigratorError) -> Never:
    print(repr(exc), file=sys.stderr)
    sys.exit(exc.exitcode)


class BaseMigratorError(Exception):
    """Each individual error message will have its own error code.
    This is the way the caller (the Nublado controller) will ascertain
    why a particular file migration attempt failed.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.exitcode = 3  # Unknown error


class NoSourceUserDirectoryError(BaseMigratorError):
    """The source directory does not exist."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.exitcode = 4  # No source directory


class NoTargetUserDirectoryError(BaseMigratorError):
    """The target directory does not exist."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.exitcode = 5  # No target directory


class CopyError(BaseMigratorError):
    """Something went wrong with file copy."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.exitcode = 6  # File permission error


class CopyPermissionError(BaseMigratorError):
    """Something went wrong with file permissions."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.exitcode = 7  # File permission error
