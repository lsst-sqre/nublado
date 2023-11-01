"""Model for lab spawn and deletion events."""

from __future__ import annotations

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


class Event(BaseModel):
    """One lab operation event for a user.

    This model is not directly returned by any handler. Instead, it is
    converted to a server-sent event via its `to_sse` method.
    """

    type: EventType = Field(..., title="Type", description="Type of the event")

    message: str = Field(
        ..., title="Message", description="User-visible message for this event"
    )

    progress: int | None = Field(
        None,
        title="Percentage",
        description=(
            "Estimated competion percentage of operation. For spawn events"
            " after the Kubernetes objects have been created, this is"
            " a mostly meaningless number to make the progress bar move, since"
            " we have no way to know how many events in total there will be."
        ),
        le=100,
        gt=0,
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
