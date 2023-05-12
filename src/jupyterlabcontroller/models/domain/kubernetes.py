"""Data types for interacting with Kubernetes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Coroutine, Optional, Self

from kubernetes_asyncio.client import V1ContainerImage, V1Pod

from .docker import DockerReference

__all__ = [
    "KubernetesNodeImage",
    "KubernetesPodEvent",
    "KubernetesPodPhase",
    "KubernetesEvent",
    "KubernetesPodWatchInfo",
    "KubernetesKindMethodContainer",
    "KubernetesKindMethodMapper",
]


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


class KubernetesPodPhase(str, Enum):
    """One of the valid phases reported in the status section of a Pod."""

    PENDING = "Pending"
    RUNNING = "Running"
    SUCCEEDED = "Succeeded"
    FAILED = "Failed"
    UNKNOWN = "Unknown"


@dataclass
class KubernetesPodEvent:
    """Represents an event seen while waiting for pod startup."""

    message: str
    """Message in the Kubernetes event."""

    phase: KubernetesPodPhase
    """Current phase of the pod."""

    error: Optional[str] = None
    """Additional error accompanying this event (usually from the pod)."""

    @property
    def done(self) -> bool:
        """`True` if the pod has started or definitively failed to start.

        An unknown phase is considered a failure. The Kubernetes documentation
        says that this can happen when the node on which the pod is supposed
        to be running cannot be contacted, which is a sufficiently broken
        state that we should consider the spawn a failure rather than waiting
        to hope it will fix itself.
        """
        return self.phase != KubernetesPodPhase.PENDING


@dataclass
class KubernetesEvent:
    """Repackaging of yielded event to regularize some fields."""

    type: str
    object: dict[str, Any]
    kind: str
    name: str
    namespace: Optional[str]

    @classmethod
    def from_event(cls, event: dict[str, Any]) -> Self:
        return cls(
            type=event["type"],
            object=event["raw_object"],
            kind=event["raw_object"]["kind"],
            name=event["raw_object"]["metadata"]["name"],
            namespace=event["raw_object"]["metadata"].get("namespace"),
        )


@dataclass
class KubernetesPodWatchInfo:
    """Packages useful info for setting up a watch for a Pod."""

    watch_args: dict[str, Any]
    initial_phase: str

    @classmethod
    def from_pod(cls, pod: V1Pod) -> Self:
        return cls(
            watch_args={
                "namespace": pod.metadata.namespace,
                "field_selector": f"metadata.name={pod.metadata.name}",
                "resource_version": pod.metadata.resource_version,
            },
            initial_phase=pod.status.phase,
        )


@dataclass
class KubernetesKindMethodContainer:
    object_type: object
    read_method: Coroutine[Any, Any, Any]
    list_method: Coroutine[Any, Any, Any]


class KubernetesKindMethodMapper:
    def __init__(self) -> None:
        self._dict: dict[str, KubernetesKindMethodContainer] = dict()

    def add(self, key: str, val: KubernetesKindMethodContainer) -> None:
        self._dict[key] = val

    def get(self, key: str) -> KubernetesKindMethodContainer:
        return self._dict[key]

    def list(self) -> list[str]:
        return list(self._dict.keys())
