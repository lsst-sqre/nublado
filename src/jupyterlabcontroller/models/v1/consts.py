"""Constants for user lab manipulation.
"""

from enum import Enum


class LabStatuses(Enum):
    STARTING = "starting"
    RUNNING = "running"
    TERMINATING = "terminating"
    FAILED = "failed"


class PodStates(Enum):
    PRESENT = "present"
    MISSING = "missing"


class EventTypes(Enum):
    COMPLETE = "complete"
    ERROR = "error"
    FAILED = "failed"
    INFO = "info"
    PROGRESS = "progress"
