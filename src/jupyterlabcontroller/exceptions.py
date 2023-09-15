"""Exceptions for the Nublado lab controller."""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar, Self

from fastapi import status
from httpx import HTTPError, HTTPStatusError, RequestError
from kubernetes_asyncio.client import ApiException
from pydantic import ValidationError
from safir.models import ErrorLocation
from safir.slack.blockkit import (
    SlackCodeBlock,
    SlackException,
    SlackMessage,
    SlackTextBlock,
    SlackTextField,
)
from safir.slack.webhook import SlackIgnoredException

__all__ = [
    "ClientRequestError",
    "DisabledError",
    "DockerRegistryError",
    "DuplicateObjectError",
    "GafaelfawrParseError",
    "GafaelfawrWebError",
    "InvalidDockerReferenceError",
    "InvalidTokenError",
    "KubernetesError",
    "LabExistsError",
    "MissingObjectError",
    "SlackWebException",
    "UnknownDockerImageError",
    "UnknownUserError",
]


class ClientRequestError(SlackIgnoredException):
    """Represents an input validation error.

    There is a global handler for this exception and all exceptions derived
    from it that returns an status code with a body that's consistent with the
    error messages generated internally by FastAPI.  It should be used for
    input and parameter validation errors that cannot be caught by FastAPI for
    whatever reason.

    Exceptions inheriting from this class should set the class variable
    ``error`` to a unique error code for that error, and the class variable
    ``status_code`` to the HTTP status code this exception should generate.

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
        location: ErrorLocation | None = None,
        field_path: list[str] | None = None,
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
                result["loc"] = [self.location.value, *self.field_path]
            else:
                result["loc"] = [self.location.value]
        return result


class InvalidDockerReferenceError(ClientRequestError):
    """Docker reference does not contain a tag.

    This is valid to Docker, but for references without a digest we require a
    tag for debugging, status display inside the lab, etc.
    """

    error = "invalid_docker_reference"


class InvalidTokenError(ClientRequestError):
    """The delegated user token is invalid."""

    error = "invalid_token"
    status_code = status.HTTP_401_UNAUTHORIZED


class PermissionDeniedError(ClientRequestError):
    """Attempt to access a resource for another user."""

    error = "permission_denied"
    status_code = status.HTTP_403_FORBIDDEN


class LabExistsError(ClientRequestError):
    """Lab creation was attempted for a user with an active lab."""

    error = "lab_exists"
    status_code = status.HTTP_409_CONFLICT


class UnknownDockerImageError(ClientRequestError):
    """Cannot find a Docker image matching the requested parameters."""

    error = "unknown_image"
    status_code = status.HTTP_400_BAD_REQUEST


class UnknownUserError(ClientRequestError):
    """No resource has been created for this user."""

    error = "unknown_user"
    status_code = status.HTTP_404_NOT_FOUND


class SlackWebException(SlackException):
    """An HTTP request to a remote service failed.

    Parameters
    ----------
    message
        Exception string value, which is the default Slack message.
    failed_at
        When the exception happened. Omit to use the current time.
    method
        Method of request.
    url
        URL of the request.
    user
        Username on whose behalf the request is being made.
    status
        Status code of failure, if any.
    body
        Body of failure message, if any.
    """

    @classmethod
    def from_exception(cls, exc: HTTPError, user: str | None = None) -> Self:
        """Create an exception from an httpx exception.

        Parameters
        ----------
        exc
            Exception from httpx.
        user
            User on whose behalf the request is being made, if known.

        Returns
        -------
        SlackWebException
            Newly-constructed exception.
        """
        if isinstance(exc, HTTPStatusError):
            status = exc.response.status_code
            method = exc.request.method
            message = f"Status {status} from {method} {exc.request.url}"
            return cls(
                message,
                method=exc.request.method,
                url=str(exc.request.url),
                user=user,
                status=status,
                body=exc.response.text,
            )
        else:
            message = f"{type(exc).__name__}: {exc!s}"
            if isinstance(exc, RequestError):
                return cls(
                    message,
                    method=exc.request.method,
                    url=str(exc.request.url),
                    user=user,
                )
            else:
                return cls(message, user=user)

    def __init__(
        self,
        message: str,
        *,
        failed_at: datetime | None = None,
        method: str | None = None,
        url: str | None = None,
        user: str | None = None,
        status: int | None = None,
        body: str | None = None,
    ) -> None:
        self.message = message
        self.method = method
        self.url = url
        self.status = status
        self.body = body
        super().__init__(message, user, failed_at=failed_at)

    def __str__(self) -> str:
        result = self.message
        if self.body:
            result += f"\nBody:\n{self.body}\n"
        return result

    def to_slack(self) -> SlackMessage:
        """Convert to a Slack message for Slack alerting.

        Returns
        -------
        SlackMessage
            Slack message suitable for posting as an alert.
        """
        message = super().to_slack()
        if self.url:
            text = f"{self.method} {self.url}" if self.method else self.url
            message.blocks.append(SlackTextField(heading="URL", text=text))
        if self.body:
            block = SlackCodeBlock(heading="Response", code=self.body)
            message.blocks.append(block)
        return message


class DockerRegistryError(SlackWebException):
    """An API call to a Docker Registry failed."""


class GafaelfawrWebError(SlackWebException):
    """An API call to Gafaelfawr failed."""


class GafaelfawrParseError(SlackException):
    """Unable to parse the reply from Gafaelfawr.

    Parameters
    ----------
    message
        Summary error message.
    error
        Detailed error message, possibly multi-line.
    """

    @classmethod
    def from_exception(cls, exc: ValidationError) -> Self:
        """Create an exception from a Pydantic parse failure.

        Parameters
        ----------
        exc
            Pydantic exception.

        Returns
        -------
        GafaelfawrParseError
            Constructed exception.
        """
        error = f"{type(exc).__name__}: {exc!s}"
        return cls("Unable to parse reply from Gafalefawr", error)

    def __init__(self, message: str, error: str) -> None:
        super().__init__(message)
        self.error = error

    def to_slack(self) -> SlackMessage:
        """Convert to a Slack message for Slack alerting.

        Returns
        -------
        SlackMessage
            Slack message suitable for posting as an alert.
        """
        message = super().to_slack()
        block = SlackCodeBlock(heading="Error", code=self.error)
        message.blocks.append(block)
        return message


class KubernetesError(SlackException):
    """An API call to Kubernetes failed.

    Parameters
    ----------
    message
        Summary of error.
    user
        Username on whose behalf the request is being made.
    namespace
        Namespace of object being acted on.
    name
        Name of object being acted on.
    kind
        Kind of object being acted on.
    status
        Status code of failure, if any.
    body
        Body of failure message, if any.
    """

    @classmethod
    def from_exception(
        cls,
        message: str,
        exc: ApiException,
        *,
        user: str | None = None,
        kind: str | None = None,
        namespace: str | None = None,
        name: str | None = None,
    ) -> Self:
        """Create an exception from a Kubernetes API exception.

        Parameters
        ----------
        message
            Brief explanation of what was being attempted.
        exc
            Kubernetes API exception.
        user
            User on whose behalf the operation was being performed.
        kind
            Kind of object being acted on.
        namespace
            Namespace of object being acted on.
        name
            Name of object being acted on.

        Returns
        -------
        KubernetesError
            Newly-created exception.
        """
        return cls(
            message,
            user=user,
            kind=kind,
            namespace=namespace,
            name=name,
            status=exc.status,
            body=exc.body if exc.body else exc.reason,
        )

    def __init__(
        self,
        message: str,
        *,
        user: str | None = None,
        kind: str | None = None,
        namespace: str | None = None,
        name: str | None = None,
        status: int | None = None,
        body: str | None = None,
    ) -> None:
        super().__init__(message, user)
        self.message = message
        self.kind = kind
        self.namespace = namespace
        self.name = name
        self.status = status
        self.body = body

    def __str__(self) -> str:
        result = self._summary()
        if self.body:
            result += f": {self.body}"
        return result

    def to_slack(self) -> SlackMessage:
        """Convert to a Slack message for Slack alerting.

        Returns
        -------
        SlackMessage
            Slack message suitable for posting as an alert.
        """
        message = super().to_slack()
        message.message = self._summary()
        if self.status:
            field = SlackTextField(heading="Status", text=str(self.status))
            message.fields.append(field)
        if self.name:
            kind = f"{self.kind} " if self.kind else ""
            if self.namespace:
                obj = f"{kind}{self.namespace}/{self.name}"
            else:
                obj = f"{kind}{self.name}"
            message.blocks.append(SlackTextBlock(heading="Object", text=obj))
        elif self.kind:
            block = SlackTextBlock(heading="Object", text=self.kind)
            message.blocks.append(block)
        if self.body:
            code = SlackCodeBlock(heading="Error", code=self.body)
            message.blocks.append(code)
        return message

    def _summary(self) -> str:
        """Summarize the exception.

        Produces a single-line summary, used for the main part of the Slack
        message and part of the stringification.
        """
        result = self.message
        if self.name or self.kind or self.status:
            result += " ("
            if self.name:
                kind = f"{self.kind} " if self.kind else ""
                if self.namespace:
                    result += f"{kind}{self.namespace}/{self.name}"
                else:
                    result += f"{kind}{self.name}"
                if self.status:
                    result += ", "
            elif self.kind:
                result += self.kind
                if self.status:
                    result += ", "
            if self.status:
                result += f"status {self.status}"
            result += ")"
        return result


class MissingObjectError(SlackException):
    """An expected Kubernetes object is missing.

    Parameters
    ----------
    message
        Summary of error.
    user
        Username on whose behalf the request is being made.
    kind
        Kind of Kubernetes object that is missing.
    namespace
        Namespace of object being acted on.
    name
        Name of object being acted on.
    """

    def __init__(
        self,
        message: str,
        *,
        user: str | None = None,
        kind: str,
        namespace: str | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(message, user)
        self.kind = kind
        self.namespace = namespace
        self.name = name

    def to_slack(self) -> SlackMessage:
        """Convert to a Slack message for Slack alerting.

        Returns
        -------
        SlackMessage
            Slack message suitable for posting as an alert.
        """
        message = super().to_slack()
        if self.name:
            if self.namespace:
                obj = f"{self.kind} {self.namespace}/{self.name}"
            else:
                obj = f"{self.kind} {self.name}"
        else:
            if self.namespace:
                obj = f"{self.kind} (namespace: {self.namespace})"
            else:
                obj = self.kind
        message.blocks.append(SlackTextBlock(heading="Object", text=obj))
        return message


class MissingSecretError(MissingObjectError):
    """Secret specified in the controller configuration was not found."""

    def __init__(self, message: str, namespace: str, name: str) -> None:
        super().__init__(
            message, kind="Secret", namespace=namespace, name=name
        )


class DuplicateObjectError(SlackException):
    """Multiple Kubernetes objects were found when one was expected.

    Parameters
    ----------
    message
        Summary of error.
    user
        Username on whose behalf the request is being made.
    kind
        Kind of Kubernetes object that was duplicated.
    namespace
        Namespace of object being acted on.
    """

    def __init__(
        self,
        message: str,
        *,
        user: str | None = None,
        kind: str,
        namespace: str | None = None,
    ) -> None:
        super().__init__(message, user)
        self.message = message
        self.kind = kind
        self.namespace = namespace

    def to_slack(self) -> SlackMessage:
        """Convert to a Slack message for Slack alerting.

        Returns
        -------
        SlackMessage
            Slack message suitable for posting as an alert.
        """
        message = super().to_slack()
        obj = f"{self.kind} {self.namespace}" if self.namespace else self.kind
        message.blocks.append(SlackTextBlock(heading="Object", text=obj))
        return message


class FileserverCreationError(ClientRequestError):
    """An error occured while trying to create a user fileserver."""

    error = "fileserver_creation_failed"
    status_code = status.HTTP_400_BAD_REQUEST


class DisabledError(SlackException):
    """An attempt was made to use a disabled service."""
