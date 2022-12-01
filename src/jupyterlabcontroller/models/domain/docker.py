import base64
import json
from dataclasses import dataclass
from typing import Dict, Optional

from structlog.stdlib import BoundLogger

from ...constants import DOCKER_SECRETS_PATH


@dataclass
class DockerCredentials:
    registry_host: str
    username: str
    password: str
    base64_auth: str


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
                registry_host=host,
                username=username,
                password=password,
                base64_auth=b64auth,
            )
            self.logger.debug(f"Added authentication for '{host}'")
