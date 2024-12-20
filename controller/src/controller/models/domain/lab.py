"""Internal models related to user labs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Annotated

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
from pydantic import BaseModel, Field
from sse_starlette import ServerSentEvent

__all__ = [
    "Event",
    "EventType",
    "LabObjectNames",
    "LabObjects",
    "LabStateObjects",
]


class EventType(Enum):
    """Type of message."""

    COMPLETE = "complete"
    ERROR = "error"
    FAILED = "failed"
    INFO = "info"


class Event(BaseModel):
    """One lab operation event for a user.

    This model is not directly returned by any handler. Instead, it is
    converted to a server-sent event via its ``to_sse`` method.
    """

    type: Annotated[
        EventType, Field(title="Type", description="Type of the event")
    ]

    message: Annotated[
        str,
        Field(
            title="Message", description="User-visible message for this event"
        ),
    ]

    progress: Annotated[
        int | None,
        Field(
            title="Percentage",
            description=(
                "Estimated competion percentage of operation. For spawn events"
                " after the Kubernetes objects have been created, this is"
                " a mostly meaningless number to make the progress bar move,"
                " since we have no way to know how many events in total there"
                " will be."
            ),
            le=100,
            gt=0,
        ),
    ] = None

    @property
    def done(self) -> bool:
        """Whether this event indicates the event stream should stop."""
        return self.type in (EventType.COMPLETE, EventType.FAILED)

    def to_sse(self) -> ServerSentEvent:
        """Convert to event suitable for sending to the client.

        Returns
        -------
        sse_starlette.ServerSentEvent
            Converted form of the event.
        """
        data: dict[str, str | int] = {"message": self.message}
        if self.progress:
            data["progress"] = self.progress
        return ServerSentEvent(data=json.dumps(data), event=self.type.value)


@dataclass
class LabObjectNames:
    """Names for the key Kubernetes objects making up a user's lab.

    An instance of this object contains the names for a specific user, named
    in the ``username`` field.

    Only the objects that need to be retrieved from Kubernetes in order to
    reconcile state need to be named here. The rest can be internal
    implementation details of `~controller.services.builder.lab.LabBuilder`.
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
