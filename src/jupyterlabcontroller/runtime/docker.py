import base64
import json
from typing import Dict

from ..models.v1.domain.docker import DockerCredentials

docker_credentials: Dict[str, DockerCredentials] = {}


def load_docker_credentials() -> None:
    try:
        with open("/etc/secrets/.dockerconfigjson") as f:
            credstore = json.loads(f.read())
            for host in credstore["auths"]:
                b64auth = credstore["auths"][host]["auth"]
                basic_auth = base64.b64decode(b64auth).decode()
                username, password = basic_auth.split(":", 1)
                docker_credentials[host] = DockerCredentials(
                    registry_host=host, username=username, password=password
                )
    except FileNotFoundError:
        # It's possible we're only using unauthenticated registries
        pass
