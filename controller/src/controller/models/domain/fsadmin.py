"""Models for the fsadmin state."""

from dataclasses import dataclass

from kubernetes_asyncio.client import (
    V1Namespace,
    V1PersistentVolumeClaim,
    V1Pod,
)

__all__ = [
    "FSAdminObjects",
]


@dataclass
class FSAdminObjects:
    """All of the Kubernetes objects making up a filesystem admin
    environment.
    """

    namespace: V1Namespace
    """Namespace for the FSAdmin pod."""

    pvcs: list[V1PersistentVolumeClaim]
    """Persistent volume claims."""

    pod: V1Pod
    """The FSAdmin pod itself."""
