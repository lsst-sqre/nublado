"""Exceptions for the RSP REST spawner.

JupyterHub catches all exceptions derived from `Exception` and treats them the
same, so the distinction between exceptions is just for better error reporting
and improved code readability.
"""

from typing import Self

from httpx import HTTPError, HTTPStatusError, RequestError

__all__ = [
    "ControllerWebError",
    "DiscoveryError",
    "InvalidAuthStateError",
    "MissingFieldError",
    "SpawnFailedError",
]


class ControllerWebError(Exception):
    """Failure to talk to the lab controller API.

    Parameters
    ----------
    message
        Exception string value, which is the default Slack message.
    method
        Method of request.
    url
        URL of the request.
    status
        Status code of failure, if any.
    reason
        Reason string of failure, if any.
    body
        Body of failure message, if any.
    """

    @classmethod
    def from_exception(cls, exc: HTTPError) -> Self:
        """Create an exception from an httpx exception.

        Parameters
        ----------
        exc
            Exception from httpx.

        Returns
        -------
        ControllerWebError
            Newly-constructed exception.
        """
        if isinstance(exc, HTTPStatusError):
            status = exc.response.status_code
            method = exc.request.method
            message = f"Status {status} from {method} {exc.request.url}"
            return cls(
                message,
                method=exc.request.method,
                url=str(exc.request.url),
                status=status,
                reason=exc.response.reason_phrase,
                body=exc.response.text,
            )
        else:
            message = f"{type(exc).__name__}: {exc!s}"
            if isinstance(exc, RequestError):
                return cls(
                    message,
                    method=exc.request.method,
                    url=str(exc.request.url),
                )
            else:
                return cls(message)

    def __init__(
        self,
        message: str,
        *,
        method: str | None = None,
        url: str | None = None,
        status: int | None = None,
        reason: str | None = None,
        body: str | None = None,
    ) -> None:
        self.message = message
        self.method = method
        self.url = url
        self.status = status
        self.reason = reason
        self.body = body
        super().__init__(message)

    def __str__(self) -> str:
        result = self.message
        if self.body:
            result += f"\nBody:\n{self.body}\n"
        return result


class DiscoveryError(Exception):
    """Service discovery of the Nublado controller failed."""


class InvalidAuthStateError(Exception):
    """The JupyterHub auth state for the user contains no token."""


class MissingFieldError(Exception):
    """The reply from the lab controller is missing a required field."""


class SpawnFailedError(Exception):
    """The lab controller reports that the spawn failed."""
