from dataclasses import dataclass
from enum import auto

from .enums import NubladoEnum, NubladoTitleEnum


@dataclass
class Secret:
    data: dict[str, str]
    secret_type: str = "Opaque"


class ObjectOperation(NubladoEnum):
    CREATION = auto()
    DELETION = auto()


class K8sPodPhase(NubladoTitleEnum):
    PENDING = auto()
    RUNNING = auto()
    SUCCEEDED = auto()
    FAILED = auto()
    UNKNOWN = auto()
