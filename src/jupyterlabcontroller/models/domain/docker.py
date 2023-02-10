"""Domain models for talking to the Docker API."""

import base64
from dataclasses import dataclass
from typing import Self


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
