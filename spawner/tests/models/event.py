"""Event model for jupyterlab-controller."""

from enum import Enum

from pydantic import Model

"""GET /nublado/spawner/v1/labs/username/events"""


class EventTypes(Enum):
    COMPLETE = "complete"
    ERROR = "error"
    FAILED = "failed"
    INFO = "info"
    PROGRESS = "progress"


class Event(Model):
    data: str
    event: EventTypes
    sent: bool = False
