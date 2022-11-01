from typing import Optional

from fastapi import Depends
from kubernetes_asyncio.client import ApiClient
from safir.dependencies.logger import logger_dependency
from structlog.stdlib import BoundLogger

from ..models.v1.domain.config import Config
from ..storage.docker import DockerClient
from ..storage.prepuller import PrepullerClient
from .config import configuration_dependency
from .docker import docker_client_dependency
from .k8s import k8s_api_dependency


class PrepullerClientDependency:
    _prepuller_client: Optional[PrepullerClient] = None

    async def __call__(
        self,
        logger: BoundLogger = Depends(logger_dependency),
        api: BoundLogger = Depends(k8s_api_dependency),
        config: Config = Depends(configuration_dependency),
        docker_client: DockerClient = Depends(docker_client_dependency),
    ) -> PrepullerClient:
        if self._prepuller_client is None:
            self.prepuller_client(
                logger=logger,
                api=api,
                config=config,
                docker_client=docker_client,
            )
        return self.get_prepuller_client()

    def get_prepuller_client(self) -> PrepullerClient:
        assert self._prepuller_client is not None
        return self._prepuller_client

    def prepuller_client(
        self,
        logger: BoundLogger,
        api: ApiClient,
        config: Config,
        docker_client: DockerClient,
    ) -> None:
        self._prepuller_client = PrepullerClient(
            logger=logger, api=api, config=config, docker_client=docker_client
        )


prepuller_client_dependency = PrepullerClientDependency()
