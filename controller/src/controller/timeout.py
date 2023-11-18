"""Timeout class for Kubernetes operations."""

from __future__ import annotations

from datetime import timedelta

from safir.datetime import current_datetime

__all__ = ["Timeout"]


class Timeout:
    """Track a cumulative timeout on a series of operations.

    Many Nublado controller operations involve operations that support
    individual timeouts, where all operations must complete within a total
    timeout. Examples include spawning a lab or creating a user file server.
    This class encapsulates that type of timeout and provides methods to
    retrieve timeouts for individual operations.
    """

    def __init__(self, timeout: timedelta) -> None:
        self._timeout = timeout
        self._start = current_datetime(microseconds=True)

    def elapsed(self) -> float:
        """Elapsed time since the timeout started.

        Returns
        -------
        float
            Seconds elapsed since the object was created.
        """
        now = current_datetime(microseconds=True)
        return (now - self._start).total_seconds()

    def error(self, operation: str) -> str:
        """Generate an error message for an expired timeout.

        The message will be based on the time since the class was created,
        regardless of whether this is longer than the initially configured
        timeout.

        Parameters
        ----------
        operation
            Operation that timed out.
        """
        return f"{operation} timed out after {self.elapsed()}s"

    def left(self) -> float:
        """Return the amount of time remaining in seconds.

        Returns
        -------
        timedelta
            Time remaining in the timeout.

        Raises
        ------
        TimeoutError
            Raised if the timeout has expired.
        """
        now = current_datetime(microseconds=True)
        left = (self._timeout - (now - self._start)).total_seconds()
        if left <= 0.0:
            raise TimeoutError(self.error("Operation"))
        return left
