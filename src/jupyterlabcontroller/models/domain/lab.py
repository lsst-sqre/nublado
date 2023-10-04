"""Internal models related to user labs."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from kubernetes_asyncio.client.models import (
    V1ConfigMap,
    V1Namespace,
    V1NetworkPolicy,
    V1PersistentVolumeClaim,
    V1Pod,
    V1ResourceQuota,
    V1Secret,
    V1Service,
)
from safir.asyncio import AsyncMultiQueue

from ..v1.event import Event
from ..v1.lab import UserLabState

__all__ = [
    "LabObjects",
    "UserLab",
]


@dataclass
class LabObjects:
    """All of the Kubernetes objects making up a user's lab."""

    namespace: V1Namespace
    """Namespace holding the user's lab."""

    config_maps: list[V1ConfigMap]
    """Config maps used by the lab pod."""

    network_policy: V1NetworkPolicy
    """Network policy for the lab."""

    pvcs: list[V1PersistentVolumeClaim]
    """Persistent volume claims."""

    quota: V1ResourceQuota | None
    """Quota for the user's namespace, if any."""

    secrets: list[V1Secret]
    """Secrets for the user's lab."""

    service: V1Service
    """Service for talking to the user's pod."""

    pod: V1Pod
    """User's lab pod."""


@dataclass
class UserLab:
    """Collects all internal state for a user's lab."""

    state: UserLabState
    """Current state of the lab, in the form returned by status routes."""

    events: AsyncMultiQueue[Event] = field(default_factory=AsyncMultiQueue)
    """Events from the current or most recent lab operation."""

    task: asyncio.Task[None] | None = None
    """Background task monitoring the progress of a lab operation.

    These tasks are not wrapped in an `aiojobs.Spawner` because the
    `aiojobs.Job` abstraction doesn't have a done method, which we use to poll
    each running spawner to see which ones have finished.
    """
