"""Domain models for talking to the Docker API."""

import base64
import json
from dataclasses import dataclass
from typing import Dict, Optional

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


class DockerCredentialsMap:
    def __init__(
        self, logger: BoundLogger, filename: str = DOCKER_SECRETS_PATH
    ) -> None:
        self.logger = logger
        self._credentials: Dict[str, DockerCredentials] = dict()
        if filename == "":
            return
        try:
            self.load_file(filename)
        except FileNotFoundError:
            self.logger.warning(f"No credentials file at {filename}")

    def get(self, host: str) -> Optional[DockerCredentials]:
        for h in self._credentials:
            if h == host or host.endswith(f".{h}"):
                return self._credentials[h]
        return None

    def load_file(self, filename: str) -> None:
        with open(filename) as f:
            credstore = json.loads(f.read())
        self._credentials = dict()
        self.logger.debug("Removed existing Docker credentials")
        for host in credstore["auths"]:
            b64auth = credstore["auths"][host]["auth"]
            basic_auth = base64.b64decode(b64auth).decode()
            username, password = basic_auth.split(":", 1)
            self._credentials[host] = DockerCredentials(
                registry_host=host, username=username, password=password
            )
            self.logger.debug(f"Added authentication for '{host}'")
