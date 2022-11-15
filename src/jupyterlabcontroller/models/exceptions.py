from typing import TypeAlias

from kubernetes_asyncio.client.rest import ApiException


class DockerRegistryError(Exception):
    """Unknown error working with the docker registry."""

    pass


NSCreationError: TypeAlias = ApiException
