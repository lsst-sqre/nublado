from contextlib import aclosing, asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

import structlog
from httpx import AsyncClient
from kubernetes_asyncio.client.api_client import ApiClient
from safir.dependencies.http import http_client_dependency
from structlog.stdlib import BoundLogger

from .config import Configuration
from .constants import KUBERNETES_REQUEST_TIMEOUT
from .dependencies.credentials import docker_credentials_dependency
from .dependencies.map import event_map_dependency, user_map_dependency
from .dependencies.prepuller import prepuller_executor_dependency
from .models.domain.docker import DockerCredentialsMap
from .models.domain.eventmap import EventMap
from .models.domain.usermap import UserMap
from .services.form import FormManager
from .services.prepuller.executor import PrepullerExecutor
from .services.prepuller.state import PrepullerState
from .services.size import SizeManager
from .storage.docker import DockerStorageClient
from .storage.gafaelfawr import GafaelfawrStorageClient
from .storage.k8s import K8sStorageClient


@dataclass
class ProcessContext:
    config: Configuration
    http_client: AsyncClient
    k8s_client: ApiClient
    docker_credentials: DockerCredentialsMap
    prepuller_executor: PrepullerExecutor
    user_map: UserMap
    event_map: EventMap

    @classmethod
    async def from_config(cls, config: Configuration) -> "ProcessContext":
        return cls(
            config=config,
            http_client=await http_client_dependency(),
            prepuller_executor=await prepuller_executor_dependency(),
            k8s_client=ApiClient(),
            docker_credentials=await docker_credentials_dependency(),
            user_map=await user_map_dependency(),
            event_map=await event_map_dependency(),
        )

    async def aclose(self) -> None:
        await self.prepuller_executor.stop()


class Factory:
    @classmethod
    async def create(cls, config: Configuration) -> "Factory":
        logger = structlog.get_logger(config.safir.logger_name)
        context = await ProcessContext.from_config(config)
        return cls(context, logger)

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
        self._logger = logger

    async def aclose(self) -> None:
        await self._context.aclose()

    def set_logger(self, logger: BoundLogger) -> None:
        self._logger = logger

    def get_config(self) -> Configuration:
        return self._context.config

    def get_prepuller_state(self) -> PrepullerState:
        return self._context.prepuller_executor.state

    def get_user_map(self) -> UserMap:
        return self._context.user_map

    def get_event_map(self) -> EventMap:
        return self._context.event_map

    def get_http_client(self) -> AsyncClient:
        return self._context.http_client

    def get_k8s_api_client(self) -> ApiClient:
        return self._context.k8s_client

    def create_size_manager(self) -> SizeManager:
        return SizeManager(sizes=self.get_config().lab.sizes)

    def create_form_manager(self) -> FormManager:
        return FormManager(
            prepuller_arbitrator=self._context.prepuller_executor.arbitrator,
            logger=self._logger,
            http_client=self.get_http_client(),
            lab_sizes=self.get_config().lab.sizes,
        )

    def create_gafaelfawr_client(self) -> GafaelfawrStorageClient:
        return GafaelfawrStorageClient(http_client=self.get_http_client())

    def create_k8s_client(self) -> K8sStorageClient:
        return K8sStorageClient(
            k8s_api=self.get_k8s_api_client(),
            timeout=KUBERNETES_REQUEST_TIMEOUT,
            logger=self._logger,
        )

    def create_docker_client(self) -> DockerStorageClient:
        return DockerStorageClient(
            host=self.get_config().images.registry,
            repository=self.get_config().images.repository,
            logger=self._logger,
            http_client=self.get_http_client(),
        )

    # lab_manager and event_manager when we have refactored them to no
    # longer be per-user?
