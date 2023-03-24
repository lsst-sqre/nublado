"""Exceptions for the RSP REST spawner.

JupyterHub catches all exceptions derived from `Exception` and treats them the
same, so the distinction between exceptions is just for better error reporting
and improved code readability.
"""


class InvalidAuthStateError(Exception):
    """The JupyterHub auth state for the user contains no token."""


class MissingFieldError(Exception):
    """The reply from the lab controller is missing a required field."""


class SpawnFailedError(Exception):
    """The lab controller reports that the spawn failed."""
