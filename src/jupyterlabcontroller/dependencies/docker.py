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
    _secrets_path: str = DOCKER_SECRETS_PATH

    async def __call__(
        self,
        logger: BoundLogger = Depends(logger_dependency),
        http_client: AsyncClient = Depends(http_client_dependency),
        config: Config = Depends(configuration_dependency),
    ) -> DockerClient:

        return self.client()

    def client(self) -> DockerClient:
        if self._client is None:
            self._client = DockerClient(secrets_path=self._secrets_path)
        return self._client

    def get_secrets_path(self) -> str:
        return self._secrets_path

    def set_secrets_path(self, filename: str) -> None:
        self._secrets_path = filename
        self._client = DockerClient(secrets_path=self._secrets_path)


docker_client_dependency = DockerClientDependency()
