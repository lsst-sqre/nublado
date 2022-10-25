from typing import Deque, Dict

from ..models.v1.domain.event import Event


class EventDependency:
    def __call__(self) -> Dict[str, Deque[Event]]:
        user_events: Dict[str, Deque[Event]] = {}
        return user_events


event_dependency = EventDependency()
