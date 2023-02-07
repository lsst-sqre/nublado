from contextlib import aclosing, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, List

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
from .exceptions import InvalidUserError
from .models.domain.docker import DockerCredentialsMap
from .models.domain.usermap import UserMap
from .models.v1.lab import UserInfo
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

    This should generally not be accessed directly, but via the Factory, and
    really the Factory itself should be accessed as part of a Request Context
    (which for brevity, since it's used a great deal) is the class named
    Context.  And *that* should generally be referenced from the context
    dependency.
    """

    config: Configuration
    http_client: AsyncClient
    k8s_client: ApiClient
    docker_credentials: DockerCredentialsMap
    prepuller_executor: PrepullerExecutor
    user_map: UserMap
    event_manager: EventManager

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
        docker_credentials = DockerCredentialsMap(
            logger=logger, filename=credentials_file
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
                    recommended_tag=config.images.recommended_tag,
                    credentials=docker_credentials.get(
                        config.images.registry,
                    ),
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
            docker_credentials=docker_credentials,
            user_map=UserMap(),
            event_manager=EventManager(logger=logger),
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

    def get_event_manager(self) -> EventManager:
        return self._context.event_manager


@dataclass
class Context:
    """This is a RequestContext.  It contains a Factory to return the
    process singletons (part of a ProcessContext), as well as the
    token from the HTTP call, which will have a scope, and if it's a user
    token, be able to be converted to a user record (it may be an admin
    token, however), and calling details for logging.

    Handlers will generally use this via the Context dependency.
    """

    logger: BoundLogger
    token: str
    ip_address: str
    _factory: Factory

    @property
    def config(self) -> Configuration:
        return self._factory.get_config()

    @property
    def user_map(self) -> UserMap:
        return self._factory.get_user_map()

    @property
    def event_manager(self) -> EventManager:
        return self._factory.get_event_manager()

    @property
    def http_client(self) -> AsyncClient:
        return self._factory.get_http_client()

    @property
    def k8s_api_client(self) -> ApiClient:
        return self._factory.get_k8s_client()

    @property
    def docker_credentials(self) -> DockerCredentialsMap:
        return self._factory.get_docker_credentials()

    @property
    def prepuller_state(self) -> PrepullerState:
        return self._factory.get_prepuller_state()

    @property
    def prepuller_executor(self) -> PrepullerExecutor:
        return self._factory.get_prepuller_executor()

    @property
    def prepuller_arbitrator(self) -> PrepullerArbitrator:
        return PrepullerArbitrator(
            state=self.prepuller_state,
            tag_client=PrepullerTagClient(
                state=self.prepuller_state,
                config=self.config.images,
                logger=self.logger,
            ),
            config=self.config.images,
            logger=self.logger,
        )

    @property
    def size_manager(self) -> SizeManager:
        return SizeManager(sizes=self.config.lab.sizes)

    @property
    def form_manager(self) -> FormManager:
        return FormManager(
            prepuller_arbitrator=self.prepuller_arbitrator,
            logger=self.logger,
            http_client=self.http_client,
            lab_sizes=self.config.lab.sizes,
        )

    @property
    def lab_manager(self) -> LabManager:
        return LabManager(
            instance_url=self.config.runtime.instance_url,
            manager_namespace=self.config.runtime.namespace_prefix,
            user_map=self.user_map,
            event_manager=self.event_manager,
            logger=self.logger,
            lab_config=self.config.lab,
            k8s_client=self.k8s_client,
            gafaelfawr_client=self.gafaelfawr_client,
        )

    @property
    def gafaelfawr_client(self) -> GafaelfawrStorageClient:
        return GafaelfawrStorageClient(
            config=self.config, http_client=self.http_client
        )

    @property
    def k8s_client(self) -> K8sStorageClient:
        return K8sStorageClient(
            k8s_api=self.k8s_api_client,
            timeout=KUBERNETES_REQUEST_TIMEOUT,
            logger=self.logger,
        )

    @property
    def docker_client(self) -> DockerStorageClient:
        return DockerStorageClient(
            host=self.config.images.registry,
            repository=self.config.images.repository,
            logger=self.logger,
            http_client=self.http_client,
            credentials=self.docker_credentials.get(
                self.config.images.registry,
            ),
            recommended_tag=self.config.images.recommended_tag,
        )

    async def get_user(self) -> UserInfo:
        if not self.token:
            raise InvalidUserError("Could not determine user from token")
        try:
            return await self.gafaelfawr_client.get_user(self.token)
        except Exception as exc:
            raise InvalidUserError(f"{exc}")

    async def get_token_scopes(self) -> List[str]:
        return await self.gafaelfawr_client.get_scopes(self.token)

    async def get_username(self) -> str:
        user = await self.get_user()
        return user.username

    async def get_namespace(self) -> str:
        username = await self.get_username()
        return f"{self.config.runtime.namespace_prefix}-{username}"

    def rebind_logger(self, **values: Any) -> None:
        """Add the given values to the logging context."""
        self.logger = self.logger.bind(**values)
        self._factory.set_logger(self.logger)
