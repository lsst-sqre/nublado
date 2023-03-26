"""Event model for jupyterlab-controller."""

from enum import Enum

from pydantic import BaseModel, Field
from sse_starlette import ServerSentEvent

# GET /nublado/spawner/v1/labs/username/events


class EventType(Enum):
    """Type of message."""

    COMPLETE = "complete"
    ERROR = "error"
    FAILED = "failed"
    INFO = "info"
    PROGRESS = "progress"


class Event(BaseModel):
    """One spawn event for a user."""

    type: EventType = Field(..., title="Type of the event")
    data: str = Field(..., title="Content of the event")

    @property
    def done(self) -> bool:
        """Whether this event indicates the event stream should stop."""
        return self.type in (EventType.COMPLETE, EventType.FAILED)

    def to_sse(self) -> ServerSentEvent:
        """Convert to event suitable for sending to the client.

        Returns
        -------
        ServerSentEvent
            Converted form of the event.
        """
        return ServerSentEvent(data=self.data, event=self.type.value)
