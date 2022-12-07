from dataclasses import dataclass
from typing import List

from httpx import AsyncClient
from structlog.stdlib import BoundLogger

from ..config import Configuration
from ..factory import Factory
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
    factory: Factory
    token: str

    @property
    def user_map(self) -> UserMap:
        return self.factory.get_user_map()

    @property
    def event_map(self) -> EventMap:
        return self.factory.get_event_map()

    @property
    def gafaelfawr_client(self) -> GafaelfawrStorageClient:
        return self.factory.create_gafaelfawr_client()

    @property
    def k8s_client(self) -> K8sStorageClient:
        return self.factory.create_k8s_client()

    @property
    def docker_client(self) -> DockerStorageClient:
        return self.factory.create_docker_client()

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
