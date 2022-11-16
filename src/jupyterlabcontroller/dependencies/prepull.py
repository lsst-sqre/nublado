from typing import Optional

from fastapi import Depends

from ..config import Config
from ..services.prepull_executor import PrepullExecutor
from ..services.prepuller import PrepullerManager
from .config import configuration_dependency


class PrepullExecutorDependency:
    def __init__(self) -> None:
        self._config: Optional[Config] = None
        self._executor: Optional[PrepullExecutor] = None
        self._manager: Optional[PrepullerManager] = None
        # Defer initialization until first use.

    async def __call__(
        self, config: Config = Depends(configuration_dependency)
    ) -> PrepullExecutor:
        return self.executor

    def set_config(self, config: Config) -> None:
        self._config = config

    @property
    def executor(self) -> PrepullExecutor:
        if self._executor is None:
            if self._config is None:
                raise RuntimeError("Executor config must be set")
            self._executor = PrepullExecutor.initialize(config=self._config)
            self._manager = self._executor.manager
        return self._executor

    @property
    def manager(self) -> PrepullerManager:
        if self._manager is None:
            raise RuntimeError("Prepull Executor must be initialized")
        return self._manager


prepull_executor_dependency = PrepullExecutorDependency()
