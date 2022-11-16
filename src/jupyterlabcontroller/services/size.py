"""Image size service.  It takes the set of lab sizes from the config
in its constructor."""

from typing import Dict, List

import bitmath

from ..config import LabSizeDefinitions
from ..constants import LIMIT_TO_REQUEST_RATIO
from ..models.domain.form import FormSize
from ..models.v1.lab import LabSize, UserResourceQuantum, UserResources


def memory_string_to_int(memstr: str) -> int:
    if not memstr.endswith("B"):
        memstr += "B"  # This makes bitmath happy
    return int(bitmath.parse_string(memstr).bytes)


class SizeManager:
    def __init__(self, sizes: LabSizeDefinitions) -> None:
        self._sizes = sizes

    @property
    def resources(self) -> Dict[LabSize, UserResources]:
        r: Dict[LabSize, UserResources] = dict()
        for sz in self._sizes:
            cpu = self._sizes[sz].cpu
            memfld = self._sizes[sz].memory
            mem: int = 0
            if type(memfld) is int:
                mem = memfld
            else:
                # I don't think this can happen, but mypy does.
                if type(memfld) is not str:
                    raise RuntimeError(
                        f"memfld: {type(memfld)} neither str nor int"
                    )
                mem = memory_string_to_int(memfld)
            r[LabSize(sz)] = UserResources(
                requests=UserResourceQuantum(
                    cpu=cpu / LIMIT_TO_REQUEST_RATIO,
                    memory=int(mem / LIMIT_TO_REQUEST_RATIO),
                ),
                limits=UserResourceQuantum(cpu=cpu, memory=mem),
            )
        return r

    @property
    def formdata(self) -> List[FormSize]:
        """Return the text representation of our sizes in a format suitable
        for injecting into the user spawner form"""
        return [
            FormSize(
                name=x.title(),
                cpu=str((self._sizes[x]).cpu),
                memory=str((self._sizes[x]).memory),
            )
            for x in self._sizes
        ]
