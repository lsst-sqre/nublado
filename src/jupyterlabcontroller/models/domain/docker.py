from typing import Dict, TypeAlias

from pydantic import BaseModel


class DockerCredentials(BaseModel):
    registry_host: str
    username: str
    password: str
    base64_auth: str


DockerMap: TypeAlias = Dict[str, DockerCredentials]
