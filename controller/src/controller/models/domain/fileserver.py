"""Models for the fileserver state."""

import contextlib
from dataclasses import dataclass
from typing import Any

from kubernetes_asyncio.client import V1Ingress, V1Job, V1Pod, V1Service

__all__ = [
    "FileserverObjects",
    "FileserverStateObjects",
    "FileserverUserMap",
]


@dataclass
class FileserverObjects:
    """All of the Kubernetes objects making up a user's fileserver."""

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


class FileserverUserMap:
    """File server state.

    All methods are async because eventually this is going to use
    Redis. Locking will be managed external to the user map.
    """

    def __init__(self) -> None:
        self._dict: dict[str, bool] = {}

    async def get(self, key: str) -> bool:
        return self._dict.get(key, False)

    async def list(self) -> list[str]:
        return list(self._dict.keys())

    async def set(self, key: str) -> None:
        self._dict[key] = True

    async def remove(self, key: str) -> None:
        with contextlib.suppress(KeyError):
            del self._dict[key]
