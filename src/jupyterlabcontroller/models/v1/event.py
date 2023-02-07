"""Event model for jupyterlab-controller."""

from enum import auto

from sse_starlette import ServerSentEvent

from ..camelcase import CamelCaseModel
from ..enums import NubladoEnum

"""GET /nublado/spawner/v1/labs/username/events"""


class EventTypes(NubladoEnum):
    COMPLETE = auto()
    ERROR = auto()
    FAILED = auto()
    INFO = auto()
    PROGRESS = auto()


class Event(CamelCaseModel):
    data: str
    event: EventTypes
    sent: bool = False

    def toSSE(self) -> ServerSentEvent:
        """The ServerSentEvent is the thing actually emitted to the client."""
        return ServerSentEvent(data=self.data, event=self.event)
