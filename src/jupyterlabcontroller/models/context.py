from dataclasses import dataclass
from typing import Any, List

from httpx import AsyncClient
from structlog.stdlib import BoundLogger

from ..config import Configuration
from ..factory import Factory
from ..services.event import EventManager
from ..services.form import FormManager
from ..services.lab import LabManager
from ..services.size import SizeManager
from ..storage.docker import DockerStorageClient
from ..storage.gafaelfawr import GafaelfawrStorageClient
from ..storage.k8s import K8sStorageClient
from .domain.eventmap import EventMap
from .domain.usermap import UserMap
from .v1.lab import UserInfo


@dataclass
class Context:
    config: Configuration
    http_client: AsyncClient
    logger: BoundLogger
    token: str
    ip_address: str
    _factory: Factory

    @property
    def user_map(self) -> UserMap:
        return self._factory.get_user_map()

    @property
    def event_map(self) -> EventMap:
        return self._factory.get_event_map()

    @property
    def gafaelfawr_client(self) -> GafaelfawrStorageClient:
        return self._factory.create_gafaelfawr_client()

    @property
    def k8s_client(self) -> K8sStorageClient:
        return self._factory.create_k8s_client()

    @property
    def docker_client(self) -> DockerStorageClient:
        return self._factory.create_docker_client()

    @property
    def lab_manager(self) -> LabManager:
        return self._factory.create_lab_manager()

    @property
    def form_manager(self) -> FormManager:
        return self._factory.create_form_manager()

    @property
    def event_manager(self) -> EventManager:
        return self._factory.create_form_manager()

    @property
    def size_manager(self) -> SizeManager:
        return self._factory.create_size_manager()

    async def get_user(self) -> UserInfo:
        return await self.gafaelfawr_client.get_user(self.token)

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
