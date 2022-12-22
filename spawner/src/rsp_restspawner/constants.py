from enum import auto

from .enums import NubladoEnum

DROPDOWN_SENTINEL_VALUE = "use_image_from_dropdown"


class LabStatus(NubladoEnum):
    STARTING = auto()
    RUNNING = auto()
    TERMINATING = auto()
    FAILED = auto()


class PodState(NubladoEnum):
    PRESENT = auto()
    MISSING = auto()
