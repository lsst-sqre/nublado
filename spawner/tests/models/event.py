"""Event model for jupyterlab-controller."""

from enum import Enum

from pydantic import BaseModel

"""GET /nublado/spawner/v1/labs/username/events"""


class EventTypes(Enum):
    COMPLETE = "complete"
    ERROR = "error"
    FAILED = "failed"
    INFO = "info"
    PROGRESS = "progress"


class Event(BaseModel):
    data: str
    event: EventTypes
    sent: bool = False
