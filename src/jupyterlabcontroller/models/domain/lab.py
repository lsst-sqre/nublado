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
    "LabObjectNames",
    "LabObjects",
    "LabStateObjects",
    "UserLab",
]


@dataclass
class LabObjectNames:
    """Names for the key Kubernetes objects making up a user's lab.

    An instance of this object contains the names for a specific user, named
    in the ``username`` field.

    Only the objects that need to be retrieved from Kubernetes in order to
    reconcile state need to be named here. The rest can be internal
    implementation details of
    `~jupyterlabcontroller.services.builder.lab.LabBuilder`.
    """

    username: str
    """User who owns objects with these names."""

    namespace: str
    """Namespace for the lab."""

    env_config_map: str
    """Name of the config map holding the lab environment."""

    quota: str
    """Name of the resource quota object, if any."""

    pod: str
    """Name of the pod."""


@dataclass
class LabStateObjects:
    """All of the Kubernetes objects required to reconstruct lab state.

    On startup and reconciliation, these objects are retrieved from Kubernetes
    for each user with a running lab and are used to recreate the internal
    state for that user. This is a subset of the objects used to create the
    lab (see `LabObjects`).
    """

    env_config_map: V1ConfigMap
    """Config map used to hold the environment of the spawned lab."""

    quota: V1ResourceQuota | None
    """Quota for the user's namespace, if any."""

    pod: V1Pod
    """User's lab pod."""


@dataclass
class LabObjects(LabStateObjects):
    """All of the Kubernetes objects making up a user's lab."""

    namespace: V1Namespace
    """Namespace holding the user's lab."""

    config_maps: list[V1ConfigMap]
    """Config maps used by the lab pod other than that for the environment."""

    network_policy: V1NetworkPolicy
    """Network policy for the lab."""

    pvcs: list[V1PersistentVolumeClaim]
    """Persistent volume claims."""

    secrets: list[V1Secret]
    """Secrets for the user's lab."""

    service: V1Service
    """Service for talking to the user's pod."""


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
