class DockerRegistryError(Exception):
    """Unknown error working with the Docker registry."""

    pass


class IncomparableImageTypesError(Exception):
    """Image tags can only be sorted within a type."""

    pass


class NSCreationError(Exception):
    """Error while attempting namespace creation."""

    pass


class NSDeletionError(Exception):
    """Error while attempting namespace deletion."""

    pass


class WatchError(Exception):
    """Error raised when the K8s watch fails too many times in a row."""

    pass
