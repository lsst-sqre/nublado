"""Metrics events for the Nublado controller."""

from __future__ import annotations

from datetime import timedelta

from pydantic import Field
from safir.dependencies.metrics import EventMaker
from safir.metrics import EventManager, EventPayload

__all__ = [
    "ActiveLabsEvent",
    "LabEvents",
    "LabMetadata",
    "SpawnFailureEvent",
    "SpawnSuccessEvent",
]


class ActiveLabsEvent(EventPayload):
    """Current count of the number of active labs.

    Notes
    -----
    This is really a gauge metric that is measured periodically, not an event.
    For now, the Nublado controller uses the event system to log this metric,
    since that's the system we have in place. If we later have a proper
    metrics system for storing measurements, this event should move to that
    system.
    """

    count: int = Field(
        ...,
        title="Active labs",
        description="Number of currently-running labs",
    )


class LabMetadata(EventPayload):
    """Common lab metadata for events."""

    image: str = Field(
        ...,
        title="Lab image",
        description="Docker reference for the lab image",
    )

    cpu_limit: float = Field(
        ...,
        title="Lab CPU limit",
        description="Kubernetes pod limit of CPU equivalents",
    )

    memory_limit: int = Field(
        ...,
        title="Lab memory limit",
        description="Kubernetes pod limit of memory in bytes",
    )


class SpawnFailureEvent(LabMetadata):
    """A lab spawn failed."""

    username: str = Field(
        ..., title="Username", description="User who attempted to spawn a lab"
    )

    elapsed: timedelta = Field(
        ...,
        title="Duration of spawn attempt",
        description="How long the spawn took before it failed",
    )


class SpawnSuccessEvent(LabMetadata):
    """A lab spawn succeeded."""

    username: str = Field(
        ..., title="Username", description="User who spawned a lab"
    )

    elapsed: timedelta = Field(
        ...,
        title="Duration of spawn",
        description=(
            "How long the spawn took before Kubernetes resources were ready."
            " This does not include the startup time of the lab itself."
        ),
    )


class LabEvents(EventMaker):
    """Event publishers for Nublado controller events about labs.

    Attributes
    ----------
    active
        Event publisher for the number of active labs.
    spawn_failure
        Event publisher for lab spawn failures.
    spawn_success
        Event publisher for lab spawn successes.
    """

    async def initialize(self, manager: EventManager) -> None:
        self.active = await manager.create_publisher(
            "active_labs", ActiveLabsEvent
        )
        self.spawn_failure = await manager.create_publisher(
            "spawn_failure", SpawnFailureEvent
        )
        self.spawn_success = await manager.create_publisher(
            "spawn_success", SpawnSuccessEvent
        )
