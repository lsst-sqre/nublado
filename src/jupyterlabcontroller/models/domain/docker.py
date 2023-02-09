"""Domain models for talking to the Docker API."""

import base64
import json
from dataclasses import dataclass
from typing import Dict, Optional, Self

from structlog.stdlib import BoundLogger

from ...constants import DOCKER_SECRETS_PATH


@dataclass
class DockerCredentials:
    """Holds the credentials for one Docker API server."""

    registry_host: str
    """Hostname of the server for which these credentials apply."""

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
    def from_config(cls, host: str, config: dict[str, str]) -> Self:
        """Create from a Docker config entry (such as a pull secret).

        This requires the ``auth`` field be set and ignores the ``username``
        and ``password`` field.

        Parameters
        ----------
        host
            The hostname of the server for which these credentials apply.
        config
            The entry for that hostname in the configuration.

        Returns
        -------
        DockerCredentials
            The resulting credentials.
        """
        basic_auth = base64.b64decode(config["auth"].encode()).decode()
        username, password = basic_auth.split(":", 1)
        return cls(registry_host=host, username=username, password=password)


class DockerCredentialsMap:
    def __init__(
        self, logger: BoundLogger, filename: str = DOCKER_SECRETS_PATH
    ) -> None:
        self.logger = logger
        self._creds: Dict[str, DockerCredentials] = dict()
        if filename == "":
            return
        try:
            self.load_file(filename)
        except FileNotFoundError:
            self.logger.warning(f"No credentials file at {filename}")

    def get(self, host: str) -> Optional[DockerCredentials]:
        for h in self._creds:
            if h == host or host.endswith(f".{h}"):
                return self._creds[h]
        return None

    def load_file(self, filename: str) -> None:
        with open(filename) as f:
            credstore = json.loads(f.read())
        self._creds = {}
        self.logger.debug("Removed existing Docker credentials")
        for host, config in credstore["auths"].items():
            self._creds[host] = DockerCredentials.from_config(host, config)
            self.logger.debug(f"Added authentication for '{host}'")
