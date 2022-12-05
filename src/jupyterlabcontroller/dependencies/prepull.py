from typing import Optional

from fastapi import Depends
from safir.dependencies.logger import logger_dependency
from structlog.stdlib import BoundLogger

from ..config import Configuration
from ..models.v1.prepuller import PrepullerConfiguration
from ..services.prepuller.arbitrator import PrepullerArbitrator
from ..services.prepuller.executor import PrepullerExecutor
from ..services.prepuller.state import PrepullerState
from ..services.prepuller.tag_client import PrepullerTagClient
from ..storage.docker import DockerStorageClient
from ..storage.k8s import K8sStorageClient
from .config import configuration_dependency
from .storage import docker_storage_dependency, k8s_storage_dependency


class PrepullerStateDependency:
    def __init__(self) -> None:
        self._prepuller_state: Optional[PrepullerState] = None
        # Defer initialization until first use.

    async def __call__(self) -> PrepullerState:
        return self.prepuller_state

    @property
    def prepuller_state(self) -> PrepullerState:
        if self._prepuller_state is None:
            self._prepuller_state = PrepullerState()
        return self._prepuller_state


prepuller_state_dependency = PrepullerStateDependency()


class PrepullerTagClientDependency:
    def __init__(self) -> None:
        self._tag_client: Optional[PrepullerTagClient] = None
        # Defer initialization until first use.

        self._prepuller_state: Optional[PrepullerState] = None
        self._logger: Optional[BoundLogger] = None
        self._config: Optional[Configuration] = None

    def set_state(
        self,
        prepuller_state: PrepullerState,
        logger: BoundLogger,
        config: Configuration,
    ) -> None:
        self._prepuller_state = prepuller_state
        self._logger = logger
        self._config = config

    async def __call__(
        self,
        prepuller_state: PrepullerState = Depends(prepuller_state_dependency),
        logger: BoundLogger = Depends(logger_dependency),
        config: Configuration = Depends(configuration_dependency),
    ) -> PrepullerTagClient:
        return self._tag_client

    @property
    def prepuller_tag_client(self) -> PrepullerTagClient:
        if self._tag_client is None:
            self._tag_client = PrepullerTagClient(
                state=self._prepuller_state,
                logger=self._logger,
                config=self._config,
            )
        else:
            self._tag_client.logger = self._logger
        return self._tag_client


prepuller_tag_client_dependency = PrepullerTagClientDependency()


class PrepullerArbitratorDependency:
    def __init__(self) -> None:
        self._prepuller_arbitrator: Optional[PrepullerArbitrator] = None
        self._tag_client: Optional[PrepullerTagClient] = None
        self._logger: Optional[BoundLogger] = None
        self._config: Optional[PrepullerConfiguration] = None

    def set_state(
        self,
        prepuller_state: PrepullerState,
        tag_client: PrepullerTagClient,
        logger: BoundLogger,
        config: Configuration,
    ) -> None:
        self._prepuller_state = prepuller_state
        self._tag_client = tag_client
        self._logger = logger
        self._config = config.images
        self._prepuller_arbitrator = None

    async def __call__(
        self,
        prepuller_state: PrepullerState = Depends(prepuller_state_dependency),
        tag_client: PrepullerTagClient = Depends(prepuller_state_dependency),
        logger: BoundLogger = Depends(logger_dependency),
        config: Configuration = Depends(configuration_dependency),
    ) -> PrepullerArbitrator:
        self._prepuller_state = prepuller_state
        self._tag_client = tag_client
        self._logger = logger
        self._config = config.images
        return self.prepuller_arbitrator

    @property
    def prepuller_arbitrator(self) -> PrepullerArbitrator:
        if self._prepuller_state is None:
            raise RuntimeError("prepuller_state cannot be None")
        if self._tag_client is None:
            raise RuntimeError("tag_client cannot be None")
        if self._logger is None:
            raise RuntimeError("logger cannot be None")
        if self._config is None:
            raise RuntimeError("config cannot be None")
        if self._prepuller_arbitrator is None:
            self._prepuller_arbitrator = PrepullerArbitrator(
                state=self._prepuller_state,
                tag_client=self._tag_client,
                logger=self._logger,
                config=self._config,
            )
        else:
            self._prepuller_arbitrator.logger = self._logger
        return self._prepuller_arbitrator


prepuller_arbitrator_dependency = PrepullerArbitratorDependency()


class PrepullerExecutorDependency:
    def __init__(self) -> None:
        self._prepuller_executor: Optional[PrepullerExecutor] = None
        # Defer initialization until first use.

        self._prepuller_state: Optional[PrepullerState] = None
        self._k8s_client: Optional[K8sStorageClient] = None
        self._docker_client: Optional[DockerStorageClient] = None
        self._arbitrator: Optional[PrepullerArbitrator] = None
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
        self._prepuller_executor = None

    async def __call__(
        self,
        docker_client: DockerStorageClient = Depends(
            docker_storage_dependency
        ),
        k8s_client: K8sStorageClient = Depends(k8s_storage_dependency),
        arbitrator: PrepullerArbitrator = Depends(
            prepuller_arbitrator_dependency
        ),
        logger: BoundLogger = Depends(logger_dependency),
        config: Configuration = Depends(configuration_dependency),
    ) -> PrepullerExecutor:
        self._k8s_client = k8s_client
        self._docker_client = docker_client
        self._arbitrator = arbitrator
        self._logger = logger
        self._config = config
        return self.prepuller_executor

    @property
    def prepuller_executor(self) -> PrepullerExecutor:
        if self._prepuller_state is None:
            raise RuntimeError("prepuller_state cannot be None")
        if self._k8s_client is None:
            raise RuntimeError("k8s_client cannot be None")
        if self._docker_client is None:
            raise RuntimeError("docker_client cannot be None")
        if self._arbitrator is None:
            raise RuntimeError("arbitrator cannot be None")
        if self._logger is None:
            raise RuntimeError("logger cannot be None")
        if self._config is None:
            raise RuntimeError("config cannot be None")
        if self._config.runtime.namespace_prefix == "":
            raise RuntimeError("namespace cannot be empty")

        if self._prepuller_executor is None:
            self._prepuller_executor = PrepullerExecutor(
                state=self._prepuller_state,
                k8s_client=self._k8s_client,
                docker_client=self._docker_client,
                arbitrator=self._arbitrator,
                logger=self._logger,
                config=self._config.images,
                namespace=self._config.runtime.namespace_prefix,
            )
        else:
            self._prepuller_executor.logger = self._logger
        return self._prepuller_executor


prepuller_executor_dependency = PrepullerExecutorDependency()
