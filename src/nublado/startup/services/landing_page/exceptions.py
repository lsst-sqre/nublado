"""Exceptions for the CST landing page provisioner."""


class PrecheckError(Exception):
    """Initial input-files-and-home-directory sanity check failed."""


class DestinationError(Exception):
    """The destination target exists and cannot be replaced safely."""


class DestinationIsDirectoryError(DestinationError):
    """The destination target exists and is a directory."""
