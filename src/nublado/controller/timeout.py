"""Timeout class for Kubernetes operations."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Self

from .exceptions import ControllerTimeoutError

__all__ = ["Timeout"]


class Timeout:
    """Track a cumulative timeout on a series of operations.

    Many Nublado controller operations involve operations that support
    individual timeouts, where all operations must complete within a total
    timeout. Examples include spawning a lab or creating a user file server.
    This class encapsulates that type of timeout and provides methods to
    retrieve timeouts for individual operations.

    Parameters
    ----------
    operation
        Human-readable name of operation, for error reporting.
    timeout
        Duration of the timeout.
    user
        If given, user associated with the timeout, for error reporting.
    """

    def __init__(
        self, operation: str, timeout: timedelta, user: str | None = None
    ) -> None:
        self._operation = operation
        self._timeout = timeout
        self._user = user
        self._start = datetime.now(tz=UTC)

    def elapsed(self) -> float:
        """Elapsed time since the timeout started.

        Returns
        -------
        float
            Seconds elapsed since the object was created.
        """
        now = datetime.now(tz=UTC)
        return (now - self._start).total_seconds()

    @asynccontextmanager
    async def enforce(self) -> AsyncIterator[None]:
        """Enforce the timeout and translate `TimeoutError`.

        Used to wrap a block of code in `asyncio.timeout` and catch any
        `TimeoutError`, translating it into
        `~nublado.controller.exceptions.ControllerTimeoutError` with additional
        context.

        Raises
        ------
        ControllerTimeoutError
            Raised if `TimeoutError` was raised inside the enclosed operation.
        """
        try:
            async with asyncio.timeout(self.left()):
                yield
        except (ControllerTimeoutError, TimeoutError) as e:
            now = datetime.now(tz=UTC)
            raise ControllerTimeoutError(
                self._operation,
                self._user,
                started_at=self._start,
                failed_at=now,
            ) from e

    def left(self) -> float:
        """Return the amount of time remaining in seconds.

        Returns
        -------
        float
            Time remaining in the timeout in seconds.

        Raises
        ------
        ControllerTimeoutError
            Raised if the timeout has expired.
        """
        now = datetime.now(tz=UTC)
        left = (self._timeout - (now - self._start)).total_seconds()
        if left <= 0.0:
            raise ControllerTimeoutError(
                self._operation,
                self._user,
                started_at=self._start,
                failed_at=now,
            )
        return left

    def partial(self, timeout: timedelta) -> Self:
        """Create a timeout that is an extension of this timeout.

        In some cases, such as after a watch for object deletion times out, we
        want to perform several operations that fit within an overall timeout.
        This method returns a timeout that is shorter than an overall timeout,
        with the same metadata, which can be used for a sub-operation.

        Parameters
        ----------
        timeout
            Maximum duration of timeout. The newly-created timeout will be
            capped at the remaining duration of the parent timeout.

        Returns
        -------
        Timeout
            Child timeout.

        Raises
        ------
        ControllerTimeoutError
            Raised if the timeout parameter is less than 0, which may happen
            if it is constructed by subtracting some time from the remaining
            time in the timeout.
        """
        now = datetime.now(tz=UTC)
        if timeout < timedelta(seconds=0):
            raise ControllerTimeoutError(
                self._operation,
                self._user,
                started_at=self._start,
                failed_at=now,
            )
        left = self._timeout - (now - self._start)
        timeout = min(left, timeout)
        return type(self)(self._operation, timeout, self._user)
