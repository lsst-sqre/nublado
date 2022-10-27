"""Event model for jupyterlab-controller."""

from typing import Deque, Dict, TypeAlias

from pydantic import BaseModel, validator
from sse_starlette import ServerSentEvent

from ..consts import EventTypes


# It's just a repackaged ServerSentEvent with a "sent" field glued on
class Event(BaseModel, ServerSentEvent):
    sent: bool = False

    def toSSE(self) -> ServerSentEvent:
        return ServerSentEvent(data=self.data, event=self.event)

    @validator("event")
    def legal_event_type(cls, v: str) -> None:
        event_types = [x.name for x in EventTypes]
        if v not in event_types:
            raise ValueError(f"must be one of {event_types}")


EventQueue: TypeAlias = Deque[Event]
EventMap: TypeAlias = Dict[str, Event]
