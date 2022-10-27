"""Event model for jupyterlab-controller."""

from typing import Any, Deque, Dict, Optional, TypeAlias

from pydantic import BaseModel, validator
from sse_starlette import ServerSentEvent

from ..consts import event_types


# It's just a repackaged ServerSentEvent with a "sent" field glued on
class Event(BaseModel, ServerSentEvent):
    data: Optional[Any] = None
    event: Optional[str] = None
    id: Optional[int] = None
    retry: Optional[int] = None
    comment: Optional[str] = None
    sep: Optional[str] = None
    sent: bool = False

    def toSSE(self) -> ServerSentEvent:
        return ServerSentEvent(
            data=self.data,
            event=self.event,
            id=self.id,
            retry=self.retry,
            comment=self.comment,
            sep=self.sep,
        )

    @validator("event")
    def legal_event_type(cls, v: Optional[str]) -> Optional[str]:
        if v not in event_types:
            raise ValueError(f"must be one of {event_types}")
        return v


EventQueue: TypeAlias = Deque[Event]
EventMap: TypeAlias = Dict[str, EventQueue]
