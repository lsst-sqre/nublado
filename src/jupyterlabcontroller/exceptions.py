"""Exceptions for the Nublado lab controller."""

from __future__ import annotations

__all__ = [
    "DockerRegistryError",
    "GafaelfawrError",
    "InvalidDockerReferenceError",
    "InvalidUserError",
    "KubernetesError",
    "LabExistsError",
    "MissingSecretError",
    "NoUserMapError",
    "NSCreationError",
    "NSDeletionError",
    "UnknownDockerImageError",
    "UnknownUserError",
    "WaitingForObjectError",
]


class InvalidDockerReferenceError(Exception):
    """Docker reference does not contain a tag.

    This is valid to Docker, but for references without a digest we require a
    tag for debugging, status display inside the lab, etc.
    """


class UnknownDockerImageError(Exception):
    """Cannot find a Docker image matching the requested parameters."""


class DockerRegistryError(Exception):
    """An API call to a Docker Registry failed."""


class NSCreationError(Exception):
    """Error while attempting namespace creation."""


class NSDeletionError(Exception):
    """Error while attempting namespace deletion."""


class WaitingForObjectError(Exception):
    """An error occurred while waiting for object creation or deletion."""


class KubernetesError(Exception):
    """An API call to Kubernetes failed."""


class LabExistsError(Exception):
    """Lab creation was attempted for a user with an active lab."""


class NoUserMapError(Exception):
    """Lab deletion was attempted for a user without a lab."""


class GafaelfawrError(Exception):
    """An API call to Gafaelfawr failed."""


class InvalidUserError(Exception):
    """The delegated user token is invalid."""


class MissingSecretError(Exception):
    """Secret specified in the controller configuration was not found."""


class UnknownUserError(Exception):
    """No resource has been created for this user."""
