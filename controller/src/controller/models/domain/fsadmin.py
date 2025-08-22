"""Models for the fileserver state."""

from dataclasses import dataclass

from kubernetes_asyncio.client import (
    V1PersistentVolumeClaim,
    V1Pod,
)

__all__ = [
    "FSAdminObjects",
]


@dataclass
class FSAdminObjects:
    """All of the Kubernetes objects making up an fsadmin instance."""

    pod: V1Pod

    pvcs: list[V1PersistentVolumeClaim]
    """Persistent volume claims."""
