from typing import TypeAlias

from kubernetes_asyncio.client.rest import ApiException


class DockerRegistryError(Exception):
    """Unknown error working with the Docker registry."""

    pass


NSCreationError: TypeAlias = ApiException


class IncomparableImageTypesError(Exception):
    """Image tags can only be sorted within a type."""

    pass
