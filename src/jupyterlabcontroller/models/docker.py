from pydantic import BaseModel


class DockerCredentials(BaseModel):
    registry_host: str
    username: str
    password: str


class DockerRegistryError(Exception):
    """Unknown error working with the docker registry."""

    pass
