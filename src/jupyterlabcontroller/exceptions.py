"""Exceptions for the Nublado lab controller."""

from __future__ import annotations

from typing import ClassVar, Optional

from fastapi import status
from safir.models import ErrorLocation
from safir.slack.webhook import SlackIgnoredException

__all__ = [
    "DockerRegistryError",
    "GafaelfawrError",
    "InvalidDockerReferenceError",
    "InvalidTokenError",
    "KubernetesError",
    "LabExistsError",
    "MissingSecretError",
    "NSCreationError",
    "NSDeletionError",
    "UnknownDockerImageError",
    "UnknownUserError",
    "ValidationError",
    "WaitingForObjectError",
]


class ValidationError(SlackIgnoredException):
    """Represents an input validation error.

    There is a global handler for this exception and all exceptions derived
    from it that returns an HTTP 422 status code with a body that's consistent
    with the error messages generated internally by FastAPI.  It should be
    used for input and parameter validation errors that cannot be caught by
    FastAPI for whatever reason.

    Attributes
    ----------
    location
        Part of the request giving rise to the error. This can be set by
        catching the exception in the part of the code that knows where the
        data came from, setting this attribute, and re-raising the exception.
    field_path
        Field, as a hierarchical list of structure elements, within that part
        of the request giving rise to the error.  As with ``location``, can be
        set by catching and re-raising.

    Parameters
    ----------
    message
        Error message (used as the ``msg`` key).
    location
        Part of the request giving rise to the error.
    field_path
        Field, as a hierarchical list of structure elements, in that part of
        the request giving rise to the error.

    Notes
    -----
    The FastAPI body format supports returning multiple errors at a time as a
    list in the ``details`` key.  This functionality has not yet been
    implemented.
    """

    error: ClassVar[str] = "validation_failed"
    """Used as the ``type`` field of the error message.

    Should be overridden by any subclass.
    """

    status_code: ClassVar[int] = status.HTTP_422_UNPROCESSABLE_ENTITY
    """HTTP status code for this type of validation error."""

    def __init__(
        self,
        message: str,
        location: Optional[ErrorLocation] = None,
        field_path: Optional[list[str]] = None,
    ) -> None:
        super().__init__(message)
        self.location = location
        self.field_path = field_path

    def to_dict(self) -> dict[str, list[str] | str]:
        """Convert the exception to a dictionary suitable for the exception.

        Returns
        -------
        dict
            Serialized error emssage to pass as the ``detail`` parameter to a
            ``fastapi.HTTPException``.  It is designed to produce the same
            JSON structure as native FastAPI errors.
        """
        result: dict[str, list[str] | str] = {
            "msg": str(self),
            "type": self.error,
        }
        if self.location:
            if self.field_path:
                result["loc"] = [self.location.value] + self.field_path
            else:
                result["loc"] = [self.location.value]
        return result


class InvalidDockerReferenceError(ValidationError):
    """Docker reference does not contain a tag.

    This is valid to Docker, but for references without a digest we require a
    tag for debugging, status display inside the lab, etc.
    """

    error = "invalid_docker_reference"


class InvalidTokenError(ValidationError):
    """The delegated user token is invalid."""

    error = "invalid_token"
    status_code = status.HTTP_401_UNAUTHORIZED


class PermissionDeniedError(ValidationError):
    """Attempt to access a resource for another user."""

    error = "permission_denied"
    status_code = status.HTTP_403_FORBIDDEN


class LabExistsError(ValidationError):
    """Lab creation was attempted for a user with an active lab."""

    error = "lab_exists"
    status_code = status.HTTP_409_CONFLICT


class UnknownDockerImageError(ValidationError):
    """Cannot find a Docker image matching the requested parameters."""

    error = "unknown_image"
    status_code = status.HTTP_400_BAD_REQUEST


class UnknownUserError(ValidationError):
    """No resource has been created for this user."""

    error = "unknown_user"
    status_code = status.HTTP_404_NOT_FOUND


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


class GafaelfawrError(Exception):
    """An API call to Gafaelfawr failed."""


class MissingSecretError(Exception):
    """Secret specified in the controller configuration was not found."""
