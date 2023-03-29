"""Image size service.  It takes the set of lab sizes from the config
in its constructor."""

import bitmath

from ..config import LabSizeDefinition
from ..constants import LIMIT_TO_REQUEST_RATIO
from ..models.domain.form import FormSize
from ..models.v1.lab import LabSize, UserResourceQuantum, UserResources


def memory_string_to_int(memstr: str) -> int:
    if not memstr.endswith("B"):
        memstr += "B"  # This makes bitmath happy
    return int(bitmath.parse_string(memstr).bytes)


class SizeManager:
    def __init__(self, sizes: dict[LabSize, LabSizeDefinition]) -> None:
        self._sizes = sizes

    def formdata(self) -> list[FormSize]:
        """Return the text representation of our sizes in a format suitable
        for injecting into the user spawner form"""
        return [
            FormSize(
                name=x.value.title(),
                cpu=str((self._sizes[x]).cpu),
                memory=str((self._sizes[x]).memory),
            )
            for x in self._sizes
        ]

    def resources(self, size: LabSize) -> UserResources:
        cpu = self._sizes[size].cpu
        memory = memory_string_to_int(self._sizes[size].memory)
        return UserResources(
            limits=UserResourceQuantum(cpu=cpu, memory=memory),
            requests=UserResourceQuantum(
                cpu=cpu / LIMIT_TO_REQUEST_RATIO,
                memory=int(memory / LIMIT_TO_REQUEST_RATIO),
            ),
        )
