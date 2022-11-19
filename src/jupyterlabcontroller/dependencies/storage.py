from pathlib import Path
from typing import Optional

from fastapi import Depends
from httpx import AsyncClient
from kubernetes_asyncio.client import ApiClient
from safir.dependencies.http_client import http_client_dependency
from safir.dependencies.logger import logger_dependency
from structlog.stdlib import BoundLogger

from ..config import Configuration
from ..constants import (
    CONFIGURATION_PATH,
    DOCKER_SECRETS_PATH,
    KUBERNETES_REQUEST_TIMEOUT,
)
from ..models.domain.docker import DockerCredentials, DockerCredentialsMap
from ..storage.docker import DockerStorageClient
from ..storage.k8s import K8sStorageClient
from .config import configuration_dependency
from .credentials import docker_credentials_dependency


class K8sStorageDependency:
    def __init__(self) -> None:
        self._k8s_client: Optional[K8sStorageClient] = None
        self._logger: Optional[BoundLogger] = None

    def set_state(
        self, logger: BoundLogger, k8s_client: K8sStorageClient
    ) -> None:
        self._logger = logger
        self._k8s_client = k8s_client

    async def __call__(
        self,
        logger: BoundLogger = Depends(logger_dependency),
    ) -> ApiClient:
        self._logger = logger
        return self.k8s_client

    @property
    def k8s_client(self) -> K8sStorageClient:
        if self._logger is None:
            raise RuntimeError("k8s client has no logger")
        if self._k8s_client is None:
            self._k8s_client = K8sStorageClient(
                logger=self._logger,
                k8s_api=ApiClient(),
                timeout=KUBERNETES_REQUEST_TIMEOUT,
            )
        else:
            self._k8s_client.logger = self._logger
        return self._k8s_client


k8s_storage_dependency = K8sStorageDependency()


class DockerStorageDependency:
    def __init__(self) -> None:
        self._docker_client: Optional[DockerStorageClient] = None
        self._logger: Optional[BoundLogger] = None
        self._http_client: Optional[AsyncClient] = None
        self._credentials: Optional[DockerCredentials] = None
        self._config: Optional[Configuration] = None

    def set_state(
        self,
        docker_client: DockerStorageClient,
        http_client: AsyncClient,
        logger: BoundLogger,
        config: Configuration,
    ) -> None:
        self._docker_client = docker_client
        self._logger = logger
        self._http_client = http_client
        self._config = config
        docker_secrets = DOCKER_SECRETS_PATH
        if config.runtime.path != CONFIGURATION_PATH:
            docker_secrets = str(
                Path(config.runtime.path).parent / "docker_config.json"
            )
        credential_map = DockerCredentialsMap(
            filename=docker_secrets, logger=logger
        )
        self._credentials = credential_map.get(config.images.registry)

    def __call__(
        self,
        config: Configuration = Depends(configuration_dependency),
        http_client: AsyncClient = Depends(http_client_dependency),
        logger: BoundLogger = Depends(logger_dependency),
        credentials: DockerCredentialsMap = Depends(
            docker_credentials_dependency
        ),
    ) -> DockerStorageClient:
        self._config = config
        self._logger = logger
        self._http_client = http_client
        self._credentials = credentials.get(config.images.repository)
        return self.docker_client

    @property
    def docker_client(self) -> DockerStorageClient:
        if self._logger is None:
            raise RuntimeError("logger cannot be None")
        if self._http_client is None:
            raise RuntimeError("http_client cannot be None")
        if self._config is None:
            raise RuntimeError("config cannot be None")
        if self._docker_client is None:
            self._docker_client = DockerStorageClient(
                host=self._config.images.registry,
                repository=self._config.images.repository,
                http_client=self._http_client,
                logger=self._logger,
                credentials=self._credentials,
            )
        else:
            DockerStorageClient.logger = self._logger
            # http_client doesn't vary
        return self._docker_client


docker_storage_dependency = DockerStorageDependency()
