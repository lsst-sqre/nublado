from contextlib import aclosing, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

import structlog
from httpx import AsyncClient
from kubernetes_asyncio.client.api_client import ApiClient
from safir.dependencies.http_client import http_client_dependency
from structlog.stdlib import BoundLogger

from .config import Configuration
from .constants import (
    CONFIGURATION_PATH,
    DOCKER_SECRETS_PATH,
    KUBERNETES_REQUEST_TIMEOUT,
)
from .models.domain.docker import DockerCredentialsMap
from .models.domain.eventmap import EventMap
from .models.domain.usermap import UserMap
from .services.prepuller.arbitrator import PrepullerArbitrator
from .services.prepuller.executor import PrepullerExecutor
from .services.prepuller.state import PrepullerState
from .services.prepuller.tag import PrepullerTagClient
from .storage.docker import DockerStorageClient
from .storage.k8s import K8sStorageClient


@dataclass
class ProcessContext:
    """This will hold all the per-process singleton items.  This feels a
    little fragile in that the only singleton enforcement lies here and in
    how the Context dependency (which contains both this and the Request
    Context) is structured.
    """

    config: Configuration
    http_client: AsyncClient
    k8s_client: ApiClient
    docker_credentials: DockerCredentialsMap
    prepuller_executor: PrepullerExecutor
    user_map: UserMap
    event_map: EventMap

    @classmethod
    async def from_config(cls, config: Configuration) -> "ProcessContext":
        prepuller_state = PrepullerState()
        k8s_api_client = ApiClient()
        logger = structlog.get_logger(config.safir.logger_name)
        if config.runtime.path == CONFIGURATION_PATH:
            credentials_file = DOCKER_SECRETS_PATH
        else:
            credentials_file = str(
                Path(config.runtime.path).parent / "docker_config.json"
            )
        return cls(
            config=config,
            http_client=await http_client_dependency(),
            k8s_client=k8s_api_client,
            prepuller_executor=PrepullerExecutor(
                state=prepuller_state,
                k8s_client=K8sStorageClient(
                    k8s_api=k8s_api_client,
                    timeout=KUBERNETES_REQUEST_TIMEOUT,
                    logger=logger,
                ),
                docker_client=DockerStorageClient(
                    host=config.images.registry,
                    repository=config.images.repository,
                    logger=logger,
                    http_client=await http_client_dependency(),
                ),
                logger=logger,
                config=config.images,
                namespace=config.runtime.namespace_prefix,
                arbitrator=PrepullerArbitrator(
                    state=prepuller_state,
                    tag_client=PrepullerTagClient(
                        state=prepuller_state,
                        config=config.images,
                        logger=logger,
                    ),
                    config=config.images,
                    logger=logger,
                ),
            ),
            docker_credentials=DockerCredentialsMap(
                logger=logger, filename=credentials_file
            ),
            user_map=UserMap(),
            event_map=EventMap(),
        )

    async def aclose(self) -> None:
        await self.prepuller_executor.stop()


class Factory:
    @classmethod
    async def create(cls, config: Configuration) -> "Factory":
        logger = structlog.get_logger(config.safir.logger_name)
        context = await ProcessContext.from_config(config)
        return cls(context=context, logger=logger)

    @classmethod
    @asynccontextmanager
    async def standalone(
        cls, config: Configuration
    ) -> AsyncIterator["Factory"]:
        factory = await cls.create(config)
        async with aclosing(factory):
            yield factory

    def __init__(
        self,
        context: ProcessContext,
        logger: BoundLogger,
    ) -> None:
        self._context = context
        self.logger = logger

    async def aclose(self) -> None:
        await self._context.aclose()

    def set_logger(self, logger: BoundLogger) -> None:
        self.logger = logger

    def get_config(self) -> Configuration:
        return self._context.config

    def get_prepuller_state(self) -> PrepullerState:
        return self._context.prepuller_executor.state

    def get_prepuller_executor(self) -> PrepullerExecutor:
        return self._context.prepuller_executor

    def get_http_client(self) -> AsyncClient:
        return self._context.http_client

    def get_k8s_client(self) -> ApiClient:
        return self._context.k8s_client

    def get_docker_credentials(self) -> DockerCredentialsMap:
        return self._context.docker_credentials

    def get_user_map(self) -> UserMap:
        return self._context.user_map

    def get_event_map(self) -> EventMap:
        return self._context.event_map
