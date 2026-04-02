"""Exceptions used by Nublado."""

from safir.slack.blockkit import SlackWebException

__all__ = ["DockerError", "DockerInvalidUrlError"]


class DockerError(SlackWebException):
    """An API call to a Docker Registry failed."""


class DockerInvalidUrlError(DockerError):
    """An invalid link was encountered while retrieving tag results."""

    def __init__(
        self, error: str, url: str, next_url: str, *, method: str
    ) -> None:
        super().__init__(f"{error}: {next_url}", method=method, url=url)
