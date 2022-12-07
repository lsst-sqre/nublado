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
from .services.events import EventManager
from .services.form import FormManager
from .services.lab import LabManager
from .services.prepuller.arbitrator import PrepullerArbitrator
from .services.prepuller.executor import PrepullerExecutor
from .services.prepuller.state import PrepullerState
from .services.prepuller.tag import PrepullerTagClient
from .services.size import SizeManager
from .storage.docker import DockerStorageClient
from .storage.gafaelfawr import GafaelfawrStorageClient
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

    def get_prepuller_executor(self) -> PrepullerExecutor:
        return self._context.prepuller_executor

    def get_user_map(self) -> UserMap:
        return self._context.user_map

    def get_event_map(self) -> EventMap:
        return self._context.event_map

    def get_http_client(self) -> AsyncClient:
        return self._context.http_client

    def get_k8s_api_client(self) -> ApiClient:
        return self._context.k8s_client

    def get_docker_credentials(self) -> DockerCredentialsMap:
        return self._context.docker_credentials

    def create_size_manager(self) -> SizeManager:
        return SizeManager(sizes=self.get_config().lab.sizes)

    def create_form_manager(self) -> FormManager:
        return FormManager(
            prepuller_arbitrator=self._context.prepuller_executor.arbitrator,
            logger=self._logger,
            http_client=self.get_http_client(),
            lab_sizes=self.get_config().lab.sizes,
        )

    def create_lab_manager(self) -> LabManager:
        return LabManager(
            instance_url=self.get_config().runtime.instance_url,
            manager_namespace=self.get_config().runtime.namespace_prefix,
            user_map=self.get_user_map(),
            logger=self._logger,
            lab_config=self.get_config().lab,
            k8s_client=self.create_k8s_client(),
            gafaelfawr_client=self.create_gafaelfawr_client(),
        )

    def create_event_manager(self) -> EventManager:
        return EventManager(
            logger=self._logger, event_map=self.get_event_map()
        )

    # lab_manager and event_manager when we have refactored them to no
    # longer be per-user?

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
