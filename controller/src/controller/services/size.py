"""Image size service."""

import bitmath

from ..config import LabSizeDefinition
from ..constants import LIMIT_TO_REQUEST_RATIO
from ..models.domain.form import FormSize
from ..models.v1.lab import LabResources, LabSize, ResourceQuantity


def memory_string_to_int(memstr: str) -> int:
    if not memstr.endswith("B"):
        memstr += "B"  # This makes bitmath happy
    return int(bitmath.parse_string(memstr).bytes)


class SizeManager:
    """Operations on image sizes.

    Parameters
    ----------
    sizes
        Size definitions from the lab controller configuration.
    """

    def __init__(self, sizes: dict[LabSize, LabSizeDefinition]) -> None:
        self._sizes = sizes

    def formdata(self) -> list[FormSize]:
        """Return available sizes for injecting into the spawner form.

        Returns
        -------
        list of FormSize
            Representation of sizes suitable for injecting into the user
            spawner form.
        """
        return [
            FormSize(
                name=x.value.title(),
                cpu=str((self._sizes[x]).cpu),
                memory=str((self._sizes[x]).memory),
            )
            for x in self._sizes
        ]

    def resources(self, size: LabSize) -> LabResources:
        cpu = self._sizes[size].cpu
        memory = memory_string_to_int(self._sizes[size].memory)
        return LabResources(
            limits=ResourceQuantity(cpu=cpu, memory=memory),
            requests=ResourceQuantity(
                cpu=cpu / LIMIT_TO_REQUEST_RATIO,
                memory=int(memory / LIMIT_TO_REQUEST_RATIO),
            ),
        )

    def size_from_resources(self, resources: LabResources) -> LabSize:
        """Determine the lab size given the resource constraints.

        This is used by reconciliation of internal data against Kubernetes.

        Parameters
        ----------
        resources
            Discovered lab resources from Kubernetes.

        Returns
        -------
        LabSize
            The corresponding lab size if one of the known sizes matches. If
            not, returns ``LabSize.custom``.
        """
        limits = resources.limits
        for size, definition in self._sizes.items():
            memory = memory_string_to_int(definition.memory)
            if definition.cpu == limits.cpu and memory == limits.memory:
                return size
        return LabSize.CUSTOM
