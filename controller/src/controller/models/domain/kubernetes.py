"""Data types for interacting with Kubernetes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, Self

from kubernetes_asyncio.client import (
    V1ContainerImage,
    V1ObjectMeta,
    V1Pod,
    V1Toleration,
)
from pydantic import BaseModel, Field, model_validator

from .docker import DockerReference

__all__ = [
    "KubernetesModel",
    "KubernetesNodeImage",
    "PodPhase",
    "PropagationPolicy",
    "PullPolicy",
    "TaintEffect",
    "Toleration",
    "TolerationOperator",
    "VolumeAccessMode",
    "WatchEventType",
]


class KubernetesModel(Protocol):
    """Protocol for Kubernetes object models.

    kubernetes-asyncio_ doesn't currently expose type information, so this
    tells mypy that all the object models we deal with will have a metadata
    attribute.
    """

    metadata: V1ObjectMeta

    def to_dict(self, *, serialize: bool = False) -> dict[str, Any]:
        ...


class PodPhase(str, Enum):
    """One of the valid phases reported in the status section of a Pod."""

    PENDING = "Pending"
    RUNNING = "Running"
    SUCCEEDED = "Succeeded"
    FAILED = "Failed"
    UNKNOWN = "Unknown"


class PropagationPolicy(Enum):
    """Possible values for the ``propagationPolicy`` parameter to delete."""

    FOREGROUND = "Foreground"
    BACKGROUND = "Background"
    ORPHAN = "Orphan"


class PullPolicy(Enum):
    """Pull policy for Docker images in Kubernetes."""

    ALWAYS = "Always"
    IF_NOT_PRESENT = "IfNotPresent"
    NEVER = "Never"


class TaintEffect(Enum):
    """Possible effects of a pod toleration."""

    NO_SCHEDULE = "NoSchedule"
    PREFER_NO_SCHEDULE = "PreferNoSchedule"
    NO_EXECUTE = "NoExecute"


class TolerationOperator(Enum):
    """Possible operators for a toleration."""

    EQUAL = "Equal"
    EXISTS = "Exists"


class Toleration(BaseModel):
    """Represents a single pod toleration rule.

    Toleration rules describe what Kubernetes node taints a pod will tolerate,
    meaning that the pod can still be scheduled on that node even though the
    node is marked as tained.
    """

    effect: TaintEffect | None = Field(
        None,
        title="Taint effect",
        description=(
            "Taint effect to match. If `None`, match all taint effects."
        ),
    )

    key: str | None = Field(
        None,
        title="Taint key",
        description=(
            "Taint key to match. If `None`, `operator` must be `Exists`,"
            " and this combination is used to match all taints."
        ),
    )

    operator: TolerationOperator = Field(
        TolerationOperator.EQUAL,
        title="Match operator",
        description=(
            "`Exists` is equivalent to a wildcard for value and matches all"
            " possible taints of a given catgory."
        ),
    )

    toleration_seconds: int | None = Field(
        None,
        title="Duration of toleration",
        description=(
            "Defines the length of time a `NoExecute` taint is tolerated and"
            " is ignored for other taint effects. The pod will be evicted"
            " this number of seconds after the taint is added, rather than"
            " immediately (the default with no toleration). `None` says to"
            " tolerate the taint forever."
        ),
    )

    value: str | None = Field(
        None,
        title="Taint value",
        description=(
            "Taint value to match. Must be `None` if the operator is `Exists`."
        ),
    )

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.operator == TolerationOperator.EXISTS:
            if self.value:
                raise ValueError("Toleration value not supported with Exists")
        else:
            if not self.key:
                raise ValueError("Toleration key must be specified")
            if not self.value:
                raise ValueError("Toleration value must be specified")
        return self

    def to_kubernetes(self) -> V1Toleration:
        """Convert to the corresponding Kubernetes resource."""
        return V1Toleration(
            effect=self.effect.value if self.effect else None,
            key=self.key,
            operator=self.operator.value,
            toleration_seconds=self.toleration_seconds,
            value=self.value,
        )


class VolumeAccessMode(str, Enum):
    """Access mode for a persistent volume."""

    READ_WRITE_ONCE = "ReadWriteOnce"
    READ_ONLY_MANY = "ReadOnlyMany"
    READ_WRITE_MANY = "ReadWriteMany"


class WatchEventType(Enum):
    """Possible values of the ``type`` field of Kubernetes watch events."""

    ADDED = "ADDED"
    MODIFIED = "MODIFIED"
    DELETED = "DELETED"


@dataclass
class KubernetesNodeImage:
    """A cached image on a Kubernetes node.

    A cached image has one or more Docker references associated with it,
    reflecting the references by which it was retrieved.

    The references will generally be in one of two formats:

    - :samp:`{registry}/{repository}@{digest}`
    - :samp:`{registry}/{repository}:{tag}`

    Most entries will have both, but if the image was pulled by digest it's
    possible only the first will be present.
    """

    references: list[str]
    """The Docker references for the image."""

    size: int
    """Size of the image in bytes."""

    @classmethod
    def from_container_image(cls, image: V1ContainerImage) -> Self:
        """Create from a Kubernetes API object.

        Parameters
        ----------
        image
            Kubernetes API object.

        Returns
        -------
        KubernetesNodeImage
            The corresponding object.
        """
        return cls(references=image.names, size=image.size_bytes)

    @property
    def digest(self) -> str | None:
        """Determine the image digest, if possible.

        Returns
        -------
        str or None
            The digest for the image if found, or `None` if not.
        """
        for reference in self.references:
            try:
                parsed_reference = DockerReference.from_str(reference)
            except ValueError:
                continue
            if parsed_reference.digest is not None:
                return parsed_reference.digest
        return None


@dataclass
class PodChange:
    """Represents a change (not creation or deletion) of a pod."""

    phase: PodPhase
    """New phase of the pod."""

    pod: V1Pod
    """Full object for the pod that changed."""
