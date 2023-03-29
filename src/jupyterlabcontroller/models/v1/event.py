"""Event model for jupyterlab-controller."""

from enum import Enum

from pydantic import BaseModel
from sse_starlette import ServerSentEvent

"""GET /nublado/spawner/v1/labs/username/events"""


class EventTypes(Enum):
    """Type of message."""

    COMPLETE = "complete"
    ERROR = "error"
    FAILED = "failed"
    INFO = "info"
    PROGRESS = "progress"


class Event(BaseModel):
    data: str
    event: EventTypes
    sent: bool = False

    def toSSE(self) -> ServerSentEvent:
        """The ServerSentEvent is the thing actually emitted to the client."""
        return ServerSentEvent(data=self.data, event=self.event.value)
