"""Constants for user lab manipulation.
"""

from enum import Enum
from typing import Tuple


class LabStatuses(Enum):
    STARTING = "starting"
    RUNNING = "running"
    TERMINATING = "terminating"
    FAILED = "failed"


lab_statuses: Tuple[str, ...] = tuple(str(x.value) for x in LabStatuses)


class PodStates(Enum):
    PRESENT = "present"
    MISSING = "missing"


pod_states: Tuple[str, ...] = tuple(str(x.value) for x in PodStates)


class EventTypes(Enum):
    COMPLETE = "complete"
    ERROR = "error"
    FAILED = "failed"
    INFO = "info"
    PROGRESS = "progress"


event_types: Tuple[str, ...] = tuple(str(x.value) for x in EventTypes)
