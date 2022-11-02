from dataclasses import dataclass
from typing import Optional

import structlog
from httpx import AsyncClient
from kubernetes_asyncio.client import ApiClient
from safir.logging import configure_logging
from structlog.stdlib import BoundLogger

from ....storage.docker import DockerStorageClient
from ....storage.k8s import K8sStorageClient
from ..external.lab import UserInfo
from .config import Config
from .event import EventMap
from .lab import UserMap


@dataclass
class RequestContext:
    token: str
    user: UserInfo
    namespace: str


@dataclass
class ContextContainer:
    config: Config
    http_client: AsyncClient
    logger: BoundLogger
    docker_client: DockerStorageClient
    k8s_client: K8sStorageClient
    user_map: UserMap
    event_map: EventMap

    @classmethod
    def initialize(
        cls,
        config: Config,
        logger: Optional[BoundLogger] = None,
        http_client: Optional[AsyncClient] = None,
    ) -> "ContextContainer":
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

    async def aclose(self) -> None:
        await self.k8s_client.aclose()
        await self.http_client.aclose()
