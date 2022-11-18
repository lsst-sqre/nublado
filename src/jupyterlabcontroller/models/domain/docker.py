from dataclasses import dataclass
from typing import Dict, TypeAlias


@dataclass
class DockerCredentials:
    registry_host: str
    username: str
    password: str
    base64_auth: str


DockerMap: TypeAlias = Dict[str, DockerCredentials]
