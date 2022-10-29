from typing import Optional

from fastapi import Depends
from safir.dependencies.logger import logger_dependency
from structlog.stdlib import BoundLogger

from ..models.v1.external.event import EventMap
from ..storage.events import EventManager


class EventMapDependency:
    def __call__(self) -> EventMap:
        user_events: EventMap = {}
        return user_events


event_map_dependency = EventMapDependency()


class EventManagerDependency:
    _manager: Optional[EventManager] = None

    def __call__(
        self,
        logger: BoundLogger = Depends(logger_dependency),
        events: EventMap = Depends(event_map_dependency),
    ) -> EventManager:
        if self._manager is None:
            self.manager(logger=logger, events=events)
        assert self._manager is not None  # because mypy is dumb
        return self._manager

    def manager(self, logger: BoundLogger, events: EventMap) -> None:
        self._manager = EventManager(logger=logger, events=events)


event_manager_dependency = EventManagerDependency()
