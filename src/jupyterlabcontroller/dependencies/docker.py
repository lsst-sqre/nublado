import base64
import json
from typing import Dict, Optional

from ..models.v1.domain.docker import DockerCredentials as DC


class DockerCredentialsDependency:
    docker_credentials: Optional[Dict[str, DC]] = None

    async def __call__(self) -> Dict[str, DC]:
        if self.docker_credentials is None:
            self.docker_credentials = {}
            try:
                with open("/etc/secrets/.dockerconfigjson") as f:
                    credstore = json.loads(f.read())
                    for host in credstore["auths"]:
                        b64auth = credstore["auths"][host]["auth"]
                        basic_auth = base64.b64decode(b64auth).decode()
                        username, password = basic_auth.split(":", 1)
                        self.docker_credentials[host] = DC(
                            registry_host=host,
                            username=username,
                            password=password,
                        )
            except FileNotFoundError:
                # It's possible we're only using unauthenticated registries.
                pass
        return self.docker_credentials


docker_credentials_dependency = DockerCredentialsDependency()
