from ..models.v1.external.event import EventMap


class EventDependency:
    def __call__(self) -> EventMap:
        user_events: EventMap = {}
        return user_events


event_dependency = EventDependency()
