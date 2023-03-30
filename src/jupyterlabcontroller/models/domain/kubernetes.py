"""Data types for interacting with Kubernetes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Self

from kubernetes_asyncio.client import V1ContainerImage

from .docker import DockerReference

__all__ = ["KubernetesNodeImage"]


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

    size: Optional[int] = None
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
