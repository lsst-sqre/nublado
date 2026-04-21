"""Models for managing Docker credentials."""

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Self

__all__ = ["DockerCredentialStore", "DockerCredentials"]


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


class DockerCredentialStore:
    """Read and write the ``.dockerconfigjson`` syntax used by Kubernetes.

    Parameters
    ----------
    credentials
        Mapping of registry hosts to credentials, or `None` to create an
        empty credential store.
    """

    @classmethod
    def from_path(cls, path: Path) -> Self:
        """Load credentials for Docker API hosts from a file.

        Parameters
        ----------
        path
            Path to file containing credentials.

        Returns
        -------
        DockerCredentialStore
            The resulting credential store.
        """
        with path.open("r") as f:
            credentials_data = json.load(f)
        credentials = {}
        for host, config in credentials_data["auths"].items():
            credentials[host] = DockerCredentials.from_config(config)
        return cls(credentials)

    def __init__(
        self, credentials: dict[str, DockerCredentials] | None = None
    ) -> None:
        self._credentials = credentials or {}

    def get(self, host: str) -> DockerCredentials | None:
        """Get credentials for a given host.

        These may be domain credentials, so if there is no exact match, return
        the credentials for any parent domain found.

        Parameters
        ----------
        host
            Host to which to authenticate.

        Returns
        -------
        DockerCredentials or None
            The corresponding credentials or `None` if there are no
            credentials in the store for that host.
        """
        credentials = self._credentials.get(host)
        if credentials:
            return credentials
        for domain, credentials in self._credentials.items():
            if host.endswith(f".{domain}"):
                return credentials
        return None

    def set(self, host: str, credentials: DockerCredentials) -> None:
        """Set credentials for a given host.

        Parameters
        ----------
        host
            The Docker API host.
        credentials
            The credentials to use for that host.
        """
        self._credentials[host] = credentials

    def save(self, path: Path) -> None:
        """Save the credentials store in ``.dockerconfigjson`` format.

        Parameters
        ----------
        path
            Path at which to save the credential store.
        """
        data = {
            "auths": {h: c.to_config() for h, c in self._credentials.items()}
        }
        with path.open("w") as f:
            json.dump(data, f)
