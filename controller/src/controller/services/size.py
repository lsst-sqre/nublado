"""Image size service."""

import bitmath

from ..config import LabSizeDefinition
from ..models.v1.lab import LabResources, LabSize


def memory_string_to_int(memstr: str) -> int:
    """Convert a human-readable size string to a number of bytes.

    Parameters
    ----------
    memstr
        Human-readable size with possible SI suffixes.

    Returns
    -------
    int
        Equivalent as number of bytes.
    """
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
