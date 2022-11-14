"""Constants for user lab manipulation.
"""

from enum import Enum
from typing import Tuple


class LabSizes(Enum):
    # https://www.d20srd.org/srd/combat/movementPositionAndDistance.htm#bigandLittleCreaturesInCombat
    FINE = "fine"
    DIMINUTIVE = "diminutive"
    TINY = "tiny"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    HUGE = "huge"
    GARGANTUAN = "gargantuan"
    COLOSSAL = "colossal"


lab_sizes: Tuple[str, ...] = tuple(str(x.value) for x in LabSizes)


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
