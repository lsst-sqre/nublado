"""Internal models related to user labs."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional

from kubernetes_asyncio.client.models import V1Volume, V1VolumeMount
from safir.asyncio import AsyncMultiQueue

from ..v1.event import Event
from ..v1.lab import UserLabState

__all__ = [
    "LabVolumeContainer",
    "UserLab",
]


@dataclass
class LabVolumeContainer:
    volume: V1Volume
    volume_mount: V1VolumeMount


@dataclass
class UserLab:
    """Collects all internal state for a user's lab."""

    state: UserLabState
    """Current state of the lab, in the form returned by status routes."""

    events: AsyncMultiQueue[Event] = field(default_factory=AsyncMultiQueue)
    """Events from the current or most recent lab operation."""

    task: Optional[asyncio.Task[None]] = None
    """Background task monitoring the progress of a lab operation.

    These tasks are not wrapped in an `aiojobs.Spawner` because the
    `aiojobs.Job` abstraction doesn't have a done method, which we use to poll
    each running spawner to see which ones have finished.
    """
