from dataclasses import dataclass, field
from typing import List, Optional

import structlog
from httpx import AsyncClient
from kubernetes_asyncio.client import ApiClient
from safir.logging import configure_logging
from structlog.stdlib import BoundLogger

from ..config import Configuration
from ..constants import KUBERNETES_REQUEST_TIMEOUT
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
    docker_client: DockerStorageClient
    k8s_client: K8sStorageClient
    gafaelfawr_client: GafaelfawrStorageClient
    user_map: UserMap
    event_map: EventMap
    namespace: str = ""
    token: str = ""
    token_scopes: List[str] = field(default_factory=list)
    user: Optional[UserInfo] = None

    @classmethod
    def initialize(
        cls,
        config: Configuration,
        logger: Optional[BoundLogger] = None,
        http_client: Optional[AsyncClient] = None,
        docker_client: Optional[DockerStorageClient] = None,
        k8s_client: Optional[K8sStorageClient] = None,
        gafaelfawr_client: Optional[GafaelfawrStorageClient] = None,
        user_map: Optional[UserMap] = None,
        event_map: Optional[EventMap] = None,
    ) -> "Context":
        if logger is None:
            # Logger
            configure_logging(
                name=config.safir.logger_name,
                profile=config.safir.profile,
                log_level=config.safir.log_level,
            )
            logger = structlog.get_logger(config.safir.logger_name)
        if logger is None:
            raise RuntimeError("Could not get logger")
        if http_client is None:
            # HTTP Client
            http_client = AsyncClient()
        if http_client is None:
            raise RuntimeError("Could not get http_client")

        # Docker client
        if docker_client is None:
            docker_client = DockerStorageClient(
                host=config.images.registry,
                repository=config.images.repository,
                logger=logger,
                http_client=http_client,
            )
        # K8s client
        if k8s_client is None:
            k8s_client = K8sStorageClient(
                k8s_api=ApiClient(),
                timeout=KUBERNETES_REQUEST_TIMEOUT,
                logger=logger,
            )

        # Gafaelfawr client
        if gafaelfawr_client is None:
            gafaelfawr_client = GafaelfawrStorageClient(
                token="", http_client=http_client
            )

        # User-to-lab map
        if user_map is None:
            user_map = UserMap()

        # User-to-event-queue map
        if event_map is None:
            event_map = EventMap()

        return cls(
            config=config,
            http_client=http_client,
            logger=logger,
            docker_client=docker_client,
            k8s_client=k8s_client,
            gafaelfawr_client=gafaelfawr_client,
            user_map=user_map,
            event_map=event_map,
        )

    async def patch_with_token(self, token: str) -> None:
        # Getting token from request is async so we can't do it at
        # object creation time
        self.token = token
        self.gafaelfawr_client.set_token(token)
        self.logger.warning(f"Patched gf client with token '{token}'")
        self.user = await self.gafaelfawr_client.get_user()
        self.logger.warning(f"user: {self.user}")
        self.token_scopes = await self.gafaelfawr_client.get_scopes()
        self.namespace = (
            f"{self.config.runtime.namespace_prefix}-{self.user.username}"
        )
