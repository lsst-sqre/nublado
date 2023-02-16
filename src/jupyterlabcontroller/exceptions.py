class InvalidDockerReferenceError(Exception):
    """Docker reference is not valid."""

    pass


class UnknownDockerImageError(Exception):
    """Cannot find a Docker image matching the requested parameters."""

    pass


class DockerRegistryError(Exception):
    """Unknown error working with the Docker registry."""

    pass


class NSCreationError(Exception):
    """Error while attempting namespace creation."""

    pass


class NSDeletionError(Exception):
    """Error while attempting namespace deletion."""

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

    pass


class GafaelfawrError(Exception):
    """An unexpected error occurred talking to Gafaelfawr."""

    pass


class InvalidUserError(Exception):
    """Raised when a user cannot be resolved from a token."""

    pass


class MissingSecretError(Exception):
    """Raised when we try to copy a non-existent secret."""

    pass


class StateUpdateError(Exception):
    """Raised when an attempt to update prepuller state fails."""

    pass
