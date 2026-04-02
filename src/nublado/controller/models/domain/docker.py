"""Domain models for talking to the Docker API."""

import re
from dataclasses import dataclass
from typing import Self, override

__all__ = ["DockerReference"]

# Regex fragments used for Docker reference parsing.
_REGISTRY = r"(?P<registry>[^/]+)"
_REPOSITORY = r"/(?P<repository>[^:@]+)"
_TAG = r"(?::(?P<tag>[^@]+))?"
_DIGEST = r"(?:@(?P<digest>.+))?"

# Regexes to parse the two recognized types of Docker references.
_DIGEST_REGEX = re.compile(_REGISTRY + _REPOSITORY + _TAG + _DIGEST + "$")


@dataclass
class DockerReference:
    """Parses a Docker reference."""

    registry: str
    """Registry (Docker API server) hosting the image."""

    repository: str
    """Repository of images (for example, ``lsstsqre/sciplat-lab``)."""

    tag: str | None
    """Tag, if present."""

    digest: str | None
    """Digest, if present."""

    @classmethod
    def from_str(cls, reference: str) -> Self:
        """Parse a Docker reference string into its components.

        Parameters
        ----------
        reference
            Reference string.

        Returns
        -------
        DockerReference
            Resulting reference.

        Raises
        ------
        ValueError
            The reference could not be parsed. (Uses `ValueError` so that this
            can be used as a Pydantic validator.)
        """
        match = _DIGEST_REGEX.match(reference)
        if not match:
            raise ValueError(f'Invalid Docker reference "{reference}"')
        tag = match.group("tag")
        digest = match.group("digest")
        return cls(
            registry=match.group("registry"),
            repository=match.group("repository"),
            tag=tag,
            digest=digest,
        )

    @override
    def __str__(self) -> str:
        result = f"{self.registry}/{self.repository}"
        if self.tag is not None:
            result += f":{self.tag}"
        if self.digest is not None:
            result += f"@{self.digest}"
        return result
