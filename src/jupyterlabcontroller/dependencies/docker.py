from typing import Optional

from fastapi import Depends
from httpx import AsyncClient
from safir.dependencies.http_client import http_client_dependency
from safir.dependencies.logger import logger_dependency
from structlog.stdlib import BoundLogger

from ..models.v1.domain.config import Config
from ..storage.docker import DockerClient
from .config import configuration_dependency


class DockerCredentialsDependency:
    docker_client: Optional[DockerClient] = None

    async def __call__(
        self,
        logger: BoundLogger = Depends(logger_dependency),
        http_client: AsyncClient = Depends(http_client_dependency),
        config: Config = Depends(configuration_dependency),
    ) -> DockerClient:
        if self.docker_client is None:
            self.docker_client = DockerClient()
        return self.docker_client


docker_credentials_dependency = DockerCredentialsDependency()
