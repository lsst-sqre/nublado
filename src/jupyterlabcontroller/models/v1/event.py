"""Event model for jupyterlab-controller."""

import json
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
    message: str = Field(..., title="Event message")
    progress: int | None = Field(
        None, title="Progress percentage", le=100, gt=0
    )

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
        data: dict[str, str | int] = {"message": self.message}
        if self.progress:
            data["progress"] = self.progress
        return ServerSentEvent(data=json.dumps(data), event=self.type.value)
