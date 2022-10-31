from typing import Optional

from aiojobs import Scheduler
from fastapi import Depends

from ..models.v1.domain.config import Config
from .config import configuration_dependency


class SchedulerDependency:
    _scheduler: Optional[Scheduler] = None

    def __call__(
        self,
        config: Config = Depends(configuration_dependency),
    ) -> Scheduler:
        if self._scheduler is None:
            self.scheduler(config=config)
        assert self._scheduler is not None  # mypy is so dumb
        return self._scheduler

    def scheduler(self, config: Config) -> None:
        self._scheduler = Scheduler(
            close_timeout=config.kubernetes.request_timeout
        )

    async def close(self) -> None:
        if self._scheduler is not None:
            await self._scheduler.close()


scheduler_dependency = SchedulerDependency()
