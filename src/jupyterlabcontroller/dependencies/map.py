from typing import Optional

from ..models.domain.eventmap import EventMap
from ..models.domain.usermap import UserMap


class UserMapDependency:
    def __init__(self) -> None:
        self._map: Optional[UserMap] = None

    async def __call__(
        self,
    ) -> UserMap:
        if self._map is None:
            self._map = UserMap()
        return self._map


user_map_dependency = UserMapDependency()


class EventMapDependency:
    def __init__(self) -> None:
        self._map: Optional[EventMap] = None

    async def __call__(
        self,
    ) -> EventMap:
        if self._map is None:
            self._map = EventMap()
        return self._map


event_map_dependency = EventMapDependency()
