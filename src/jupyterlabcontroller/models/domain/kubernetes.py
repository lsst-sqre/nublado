"""Data types for interacting with Kubernetes."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Self

from kubernetes_asyncio.client import V1ContainerImage

from .docker import DockerReference

__all__ = [
    "KubernetesEventData",
    "KubernetesNodeImage",
    "KubernetesPodPhase",
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
class KubernetesEventData:
    """A helper class to capture the most useful data about a Kubernetes
    Event and focus on a particular field within the event's involved object.
    """

    type: str
    raw_object: dict[str, Any]
    name: str
    kind: str
    field: list[str] = field(default_factory=list)
    missing_field: bool = True
    value: Any = None

    @classmethod
    def from_kubernetes_event(
        cls, event: dict[str, Any]
    ) -> KubernetesEventData:
        raw_object = event["raw_object"]  # This will exist (I think)
        e_type = event["type"]
        name = "<unknown name>"
        kind = "<unknown kind>"
        if "metadata" in raw_object and "name" in raw_object["metadata"]:
            name = raw_object["metadata"]["name"]
        if "kind" in raw_object:
            kind = raw_object["kind"]
        return cls(
            type=e_type, name=name, kind=kind, field=[], raw_object=raw_object
        )

    def reduce_by_field(self) -> None:
        obj = self.raw_object
        if self.field:
            fldval = deepcopy(obj)
            self.missing_field = False
            for fld in self.field:
                try:
                    fldval = fldval[fld]
                except (KeyError, TypeError):
                    self.missing_field = True
                    break
            self.value = fldval
