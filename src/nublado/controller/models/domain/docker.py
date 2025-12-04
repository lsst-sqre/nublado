"""Domain models for talking to the Docker API."""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from typing import Self

__all__ = [
    "DockerCredentials",
    "DockerReference",
]

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

    def __str__(self) -> str:
        result = f"{self.registry}/{self.repository}"
        if self.tag is not None:
            result += f":{self.tag}"
        if self.digest is not None:
            result += f"@{self.digest}"
        return result


@dataclass
class DockerCredentials:
    """Holds the credentials for one Docker API server."""

    username: str
    """Authentication username."""

    password: str
    """Authentication password."""

    @property
    def authorization(self) -> str:
        """Authentication string for ``Authorization`` header."""
        return f"Basic {self.credentials}"

    @property
    def credentials(self) -> str:
        """Credentials in encoded form suitable for ``Authorization``."""
        auth_data = f"{self.username}:{self.password}".encode()
        return base64.b64encode(auth_data).decode()

    @classmethod
    def from_config(cls, config: dict[str, str]) -> Self:
        """Create from a Docker config entry (such as a pull secret).

        This requires the ``auth`` field be set and ignores the ``username``
        and ``password`` field.

        Parameters
        ----------
        config
            The entry for that hostname in the configuration.

        Returns
        -------
        DockerCredentials
            The resulting credentials.
        """
        basic_auth = base64.b64decode(config["auth"].encode()).decode()
        username, password = basic_auth.split(":", 1)
        return cls(username=username, password=password)

    def to_config(self) -> dict[str, str]:
        """Convert the credentials to a Docker config entry.

        Returns
        -------
            Docker config entry for this host.
        """
        return {
            "username": self.username,
            "password": self.password,
            "auth": self.credentials,
        }
