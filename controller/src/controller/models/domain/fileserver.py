"""Models for the fileserver state."""

from dataclasses import dataclass
from typing import Any

from kubernetes_asyncio.client import (
    V1Ingress,
    V1Job,
    V1PersistentVolume,
    V1PersistentVolumeClaim,
    V1Pod,
    V1Service,
)

__all__ = [
    "FileserverObjects",
    "FileserverStateObjects",
]


@dataclass
class FileserverObjects:
    """All of the Kubernetes objects making up a user's fileserver."""

    pvs: list[V1PersistentVolume]
    """Persistent volumes."""

    pvcs: list[V1PersistentVolumeClaim]
    """Persistent volume claims."""

    ingress: dict[str, Any]
    """``GafaelfawrIngress`` object for the fileserver."""

    service: V1Service
    """Service for reaching the fileserver."""

    job: V1Job
    """Job that runs the fileserver itself."""


@dataclass
class FileserverStateObjects:
    """Kubernetes objects used for inspecting the state of a fileserver.

    These are used during state reconciliation to determine whether a user's
    fileserver is operational. They're disjoint from the resources created
    when starting a fileserver since in this case we care about the
    ``Ingress`` and not the ``GafaelfawrIngress``, and we also care about the
    ``Pod``.
    """

    job: V1Job
    """Job that runs the fileserver."""

    pod: V1Pod | None
    """Pod of the running fileserver."""

    ingress: V1Ingress | None
    """Ingress of the running fileserver."""
