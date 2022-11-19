from typing import Optional

from fastapi import Depends
from safir.dependencies.logger import logger_dependency
from structlog.stdlib import BoundLogger

from ..config import Configuration
from ..services.prepuller import PrepullerManager
from ..storage.docker import DockerStorageClient
from ..storage.k8s import K8sStorageClient
from .config import configuration_dependency
from .storage import docker_storage_dependency, k8s_storage_dependency


class PrepullerManagerDependency:
    def __init__(self) -> None:
        self._prepuller_manager: Optional[PrepullerManager] = None
        # Defer initialization until first use.
        self._docker_client: Optional[DockerStorageClient] = None
        self._k8s_client: Optional[K8sStorageClient] = None
        self._logger: Optional[BoundLogger] = None
        self._config: Optional[Configuration] = None

    def set_state(
        self,
        logger: BoundLogger,
        k8s_client: K8sStorageClient,
        docker_client: DockerStorageClient,
        config: Configuration,
    ) -> None:
        self._logger = logger
        self._k8s_client = k8s_client
        self._docker_client = docker_client
        self._config = config
        self._prepuller_manager = None

    async def __call__(
        self,
        docker_client: DockerStorageClient = Depends(
            docker_storage_dependency
        ),
        k8s_client: K8sStorageClient = Depends(k8s_storage_dependency),
        logger: BoundLogger = Depends(logger_dependency),
        config: Configuration = Depends(configuration_dependency),
    ) -> PrepullerManager:
        self._logger = logger
        self._config = config
        self._k8s_client = k8s_client
        self._docker_client = docker_client
        return self.prepuller_manager

    @property
    def prepuller_manager(self) -> PrepullerManager:
        if self._logger is None:
            raise RuntimeError("logger cannot be None")
        if self._config is None:
            raise RuntimeError("config cannot be None")
        if self._k8s_client is None:
            raise RuntimeError("k8s_client cannot be None")
        if self._docker_client is None:
            raise RuntimeError("docker_client cannot be None")
        if self._prepuller_manager is None:
            self._prepuller_manager = PrepullerManager(
                namespace=self._config.runtime.namespace_prefix,
                logger=self._logger,
                k8s_client=self._k8s_client,
                docker_client=self._docker_client,
                config=self._config.images,
            )
        else:
            self._prepuller_manager.logger = self._logger
        return self._prepuller_manager

    async def run(self) -> None:
        if self._prepuller_manager is not None:
            await self._prepuller_manager.run()

    async def stop(self) -> None:
        if self._prepuller_manager is not None:
            await self._prepuller_manager.stop()


prepuller_manager_dependency = PrepullerManagerDependency()
