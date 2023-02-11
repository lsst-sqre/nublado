"""Data types for interacting with Kubernetes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Self

from kubernetes_asyncio.client import V1ContainerImage

__all__ = ["KubernetesNodeImage"]

# Regex fragments used for Docker reference parsing.
_REGISTRY = r"(?P<registry>[^/]+)"
_REPOSITORY = r"(?P<repository>[^:@]+)"
_DIGEST = r"@(?P<digest>.*)"

# Regexes to parse the two recognized types of Docker references.
_DIGEST_REGEX = re.compile(_REGISTRY + _REPOSITORY + _DIGEST + "$")


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
            match = _DIGEST_REGEX.match(reference)
            if match:
                return match.group("digest")
        return None
