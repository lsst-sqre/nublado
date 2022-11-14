from dataclasses import dataclass, field
from typing import List, Optional

import structlog
from fastapi import Request
from httpx import AsyncClient
from kubernetes_asyncio.client import ApiClient
from safir.logging import configure_logging
from structlog.stdlib import BoundLogger

from ..config import Config
from ..storage.docker import DockerStorageClient
from ..storage.gafaelfawr import GafaelfawrStorageClient
from ..storage.k8s import K8sStorageClient
from .domain.event import EventMap
from .domain.lab import UserMap
from .v1.lab import UserInfo


@dataclass
class Context:
    config: Config
    http_client: AsyncClient
    logger: BoundLogger
    docker_client: DockerStorageClient
    k8s_client: K8sStorageClient
    user_map: UserMap
    event_map: EventMap
    namespace: str = ""
    token: str = ""
    token_scopes: List[str] = field(default_factory=list)
    user: Optional[UserInfo] = None

    @classmethod
    def initialize(
        cls,
        config: Config,
        logger: Optional[BoundLogger] = None,
        http_client: Optional[AsyncClient] = None,
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
        docker_client = DockerStorageClient(
            config=config, logger=logger, http_client=http_client
        )
        timeout = config.kubernetes.request_timeout
        # K8s client
        k8s_client = K8sStorageClient(k8s_api=ApiClient(), timeout=timeout)

        # User-to-lab map
        user_map: UserMap = {}

        # User-to-event-queue map
        event_map: EventMap = {}

        return cls(
            config=config,
            http_client=http_client,
            logger=logger,
            docker_client=docker_client,
            k8s_client=k8s_client,
            user_map=user_map,
            event_map=event_map,
        )

    async def patch_with_request(self, request: Request) -> None:
        # Getting user and token from request are async so we can't
        # do it at object creation time.
        gafaelfawr_client = GafaelfawrStorageClient(
            request=request, http_client=self.http_client
        )
        self.token = gafaelfawr_client.token
        self.user = await gafaelfawr_client.get_user()
        self.token_scopes = await gafaelfawr_client.get_scopes()
