"""Image manager implementation for the Docker API."""

from typing import override

from structlog.stdlib import BoundLogger

from ..storage.docker import DockerStorageClient
from ._base import ImagesManager

__all__ = ["DockerImagesManager"]


class DockerImagesManager(ImagesManager):
    """Manage Nublado images using the Docker API.

    Parameters
    ----------
    docker_client
        Docker client.
    logger
        Logger to use.
    """

    def __init__(
        self, docker_client: DockerStorageClient, logger: BoundLogger
    ) -> None:
        self._client = docker_client
        self._logger = logger

    @override
    async def list_tags(self) -> set[str]:
        return await self._client.list_tags()
