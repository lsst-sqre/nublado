"""Event model for jupyterlab-controller."""

from typing import Deque, Dict, TypeAlias

from pydantic import BaseModel, validator
from sse_starlette import ServerSentEvent

from ..enums import event_types

"""GET /nublado/spawner/v1/labs/username/events"""


class Event(BaseModel):
    data: str
    event: str
    sent: bool = False

    def toSSE(self) -> ServerSentEvent:
        """The ServerSentEvent is the thing actually emitted to the client."""
        return ServerSentEvent(data=self.data, event=self.event)

    @validator("event")
    def legal_event_type(cls, v: str) -> str:
        if v not in event_types:
            raise ValueError(f"must be one of {event_types}")
        return v


EventQueue: TypeAlias = Deque[Event]
EventMap: TypeAlias = Dict[str, EventQueue]
