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


class WaitingForObjectError(Exception):
    """Error raised when something goes wrong waiting for object creation/
    deletion."""

    pass


class KubernetesError(Exception):
    """Generic error for something keeling over in the K8s layer."""

    pass


class LabExistsError(Exception):
    """Raised when lab creation is attempted for a user with an active lab."""

    pass


class NoUserMapError(Exception):
    """Raised when a user deletion is called for a user without a lab."""


class InvalidUserError(Exception):
    """Raised when a user cannot be resolved from a token."""
