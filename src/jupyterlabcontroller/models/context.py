from dataclasses import dataclass
from typing import Any, List

from httpx import AsyncClient
from kubernetes_asyncio.client.api_client import ApiClient
from structlog.stdlib import BoundLogger

from ..config import Configuration
from ..constants import KUBERNETES_REQUEST_TIMEOUT
from ..exceptions import InvalidUserError
from ..factory import Factory
from ..services.events import EventManager
from ..services.form import FormManager
from ..services.lab import LabManager
from ..services.prepuller.arbitrator import PrepullerArbitrator
from ..services.prepuller.executor import PrepullerExecutor
from ..services.prepuller.state import PrepullerState
from ..services.prepuller.tag import PrepullerTagClient
from ..services.size import SizeManager
from ..storage.docker import DockerStorageClient
from ..storage.gafaelfawr import GafaelfawrStorageClient
from ..storage.k8s import K8sStorageClient
from .domain.docker import DockerCredentialsMap
from .domain.eventmap import EventMap
from .domain.usermap import UserMap
from .v1.lab import UserInfo


@dataclass
class Context:
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
    def event_map(self) -> EventMap:
        return self._factory.get_event_map()

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
            event_map=self.event_map,
            logger=self.logger,
            lab_config=self.config.lab,
            k8s_client=self.k8s_client,
            gafaelfawr_client=self.gafaelfawr_client,
        )

    @property
    def event_manager(self) -> EventManager:
        return EventManager(
            logger=self.logger,
            event_map=self.event_map,
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
