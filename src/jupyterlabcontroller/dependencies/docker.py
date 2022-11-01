from typing import Optional

from fastapi import Depends
from httpx import AsyncClient
from safir.dependencies.http_client import http_client_dependency
from safir.dependencies.logger import logger_dependency
from structlog.stdlib import BoundLogger

from ..models.v1.consts import DOCKER_SECRETS_PATH
from ..models.v1.domain.config import Config
from ..storage.docker import DockerClient
from .config import configuration_dependency


class DockerClientDependency:
    _client: Optional[DockerClient] = None
    _logger: Optional[BoundLogger] = None
    _secrets_path: str = DOCKER_SECRETS_PATH
    _http_client: Optional[AsyncClient] = None
    _config: Optional[Config] = None

    async def __call__(
        self,
        logger: BoundLogger = Depends(logger_dependency),
        http_client: AsyncClient = Depends(http_client_dependency),
        config: Config = Depends(configuration_dependency),
    ) -> DockerClient:
        self._http_client = http_client
        self._config = config
        return self.client(
            logger=logger, http_client=http_client, config=config
        )

    def client(
        self, logger: BoundLogger, http_client: AsyncClient, config: Config
    ) -> DockerClient:
        if self._client is None:
            assert self._http_client is not None
            assert self._logger is not None
            assert self._config is not None
            self._client = DockerClient(
                logger=logger,
                http_client=http_client,
                config=config,
                secrets_path=self._secrets_path,
            )
        return self._client

    def get_secrets_path(self) -> str:
        return self._secrets_path

    def set_secrets_path(self, filename: str) -> None:
        self._secrets_path = filename
        if self._client is None:
            return  # We will initialize it when we need it, and the path
            # will be set correctly.
        # Otherwise, we have a client already and we need to change it.
        assert self._http_client is not None
        assert self._logger is not None
        assert self._config is not None
        self._client = DockerClient(
            logger=self._logger,
            http_client=self._http_client,
            config=self._config,
            secrets_path=self._secrets_path,
        )


docker_client_dependency = DockerClientDependency()
