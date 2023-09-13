"""Data types for interacting with Kubernetes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Self

from kubernetes_asyncio.client import V1ContainerImage, V1ObjectMeta
from typing_extensions import Protocol

from .docker import DockerReference

__all__ = [
    "KubernetesModel",
    "KubernetesNodeImage",
    "KubernetesPodPhase",
    "PropagationPolicy",
    "WatchEventType",
]


class KubernetesModel(Protocol):
    """Protocol for Kubernetes object models.

    kubernetes-asyncio_ doesn't currently expose type information, so this
    tells mypy that all the object models we deal with will have a metadata
    attribute.
    """

    metadata: V1ObjectMeta


class PropagationPolicy(Enum):
    """Possible values for the ``propagationPolicy`` parameter to delete."""

    FOREGROUND = "Foreground"
    BACKGROUND = "Background"
    ORPHAN = "Orphan"


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


class KubernetesPodPhase(str, Enum):
    """One of the valid phases reported in the status section of a Pod."""

    PENDING = "Pending"
    RUNNING = "Running"
    SUCCEEDED = "Succeeded"
    FAILED = "Failed"
    UNKNOWN = "Unknown"
