from dataclasses import dataclass
from enum import Enum


@dataclass
class Secret:
    data: dict[str, str]
    secret_type: str = "Opaque"


class ObjectOperation(Enum):
    CREATION = "creation"
    DELETION = "deletion"
