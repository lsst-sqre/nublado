"""Factories for Nublado tools."""

from collections.abc import AsyncGenerator
from contextlib import aclosing, asynccontextmanager
from typing import Self

from httpx import AsyncClient
from structlog import get_logger
from structlog.stdlib import BoundLogger

from .config.images import ImagesConfig
from .constants import ROOT_LOGGER
from .models.images import DockerSource, GARSource
from .services.images import (
    DockerImagesManager,
    GARImagesManager,
    ImagesManager,
)
from .storage.docker import DockerStorageClient
from .storage.gar import GARStorageClient

__all__ = ["ImagesFactory"]


class ImagesFactory:
    """Factory for Nublado image management.

    Parameters
    ----------
    config
        Image management configuration.
    logger
        Logger to use.
    """

    @classmethod
    @asynccontextmanager
    async def standalone(cls, config: ImagesConfig) -> AsyncGenerator[Self]:
        """Context manager for image management components.

        Parameters
        ----------
        config
            Image management configuration.

        Returns
        -------
        ImagesFactory
            Factory that will be shut down when the context manager exits.
        """
        logger = get_logger(ROOT_LOGGER)
        async with aclosing(cls(config, logger)) as factory:
            yield factory

    def __init__(self, config: ImagesConfig, logger: BoundLogger) -> None:
        self._config = config
        self._http_client = AsyncClient()
        self._logger = logger

    async def aclose(self) -> None:
        """Shut down the factory.

        After this method is called, the factory object is no longer valid and
        must not be used.
        """
        await self._http_client.aclose()

    def create_images_manager(self) -> ImagesManager:
        """Create a new images manager.

        Returns
        -------
        ImagesManager
            Newly-created images manager.
        """
        match self._config.source:
            case DockerSource():
                docker_client = DockerStorageClient(
                    self._config.docker_credentials_path,
                    self._http_client,
                    self._logger,
                )
                return DockerImagesManager(docker_client, self._logger)
            case GARSource():
                gar_client = GARStorageClient(self._logger)
                return GARImagesManager(gar_client, self._logger)
