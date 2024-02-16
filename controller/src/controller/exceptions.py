"""Exceptions for the Nublado lab controller."""

from __future__ import annotations

from datetime import datetime
from typing import Self

from fastapi import status
from kubernetes_asyncio.client import ApiException
from pydantic import ValidationError
from safir.datetime import format_datetime_for_logging
from safir.fastapi import ClientRequestError
from safir.models import ErrorLocation
from safir.slack.blockkit import (
    SlackBaseField,
    SlackCodeBlock,
    SlackException,
    SlackMessage,
    SlackTextBlock,
    SlackTextField,
    SlackWebException,
)

from .models.v1.lab import LabSize

__all__ = [
    "ControllerTimeoutError",
    "DockerRegistryError",
    "DuplicateObjectError",
    "GafaelfawrParseError",
    "GafaelfawrWebError",
    "InsufficientQuotaError",
    "InvalidDockerReferenceError",
    "InvalidLabSizeError",
    "InvalidTokenError",
    "KubernetesError",
    "LabDeletionError",
    "LabExistsError",
    "MissingObjectError",
    "MissingSecretError",
    "NoOperationError",
    "NotConfiguredError",
    "OperationConflictError",
    "PermissionDeniedError",
    "UnknownDockerImageError",
    "UnknownUserError",
]


class InsufficientQuotaError(ClientRequestError):
    """The user's quota is insufficient to satisfy this request."""

    error = "insufficient_quota"
    status_code = status.HTTP_403_FORBIDDEN


class InvalidDockerReferenceError(ClientRequestError):
    """Docker reference does not contain a tag.

    This is valid to Docker, but for references without a digest we require a
    tag for debugging, status display inside the lab, etc.
    """

    error = "invalid_docker_reference"


class InvalidLabSizeError(ClientRequestError):
    """The provided lab size is not one of the configured sizes."""

    error = "invalid_lab_size"

    def __init__(self, size: LabSize) -> None:
        msg = f'Invalid lab size "{size.value}"'
        super().__init__(msg, ErrorLocation.body, ["options", "size"])


class InvalidTokenError(ClientRequestError):
    """The delegated user token is invalid."""

    error = "invalid_token"
    status_code = status.HTTP_401_UNAUTHORIZED


class LabExistsError(ClientRequestError):
    """Lab creation was attempted for a user with an active lab."""

    error = "lab_exists"
    status_code = status.HTTP_409_CONFLICT


class OperationConflictError(ClientRequestError):
    """Attempt to perform an operation when another is in progress."""

    error = "operation_in_progress"
    status_code = status.HTTP_409_CONFLICT

    def __init__(self, username: str) -> None:
        msg = f"Conflicting operation for {username} already in progress"
        super().__init__(msg)


class NotConfiguredError(ClientRequestError):
    """An attempt was made to use a disabled service."""

    error = "not_supported"
    status_code = status.HTTP_404_NOT_FOUND


class PermissionDeniedError(ClientRequestError):
    """Attempt to access a resource for another user."""

    error = "permission_denied"
    status_code = status.HTTP_403_FORBIDDEN


class UnknownDockerImageError(ClientRequestError):
    """Cannot find a Docker image matching the requested parameters."""

    error = "unknown_image"
    status_code = status.HTTP_400_BAD_REQUEST


class UnknownUserError(ClientRequestError):
    """No resource has been created for this user."""

    error = "unknown_user"
    status_code = status.HTTP_404_NOT_FOUND


class ControllerTimeoutError(SlackException):
    """Wraps `TimeoutError` with additional context and Slack support.

    Parameters
    ----------
    operation
        Operation that timed out.
    user
        User associated with operation, if any.
    started_at
        Start time of the operation.
    failed_at
        Time at which the operation timed out.
    """

    def __init__(
        self,
        operation: str,
        user: str | None = None,
        *,
        started_at: datetime,
        failed_at: datetime,
    ) -> None:
        self.started_at = started_at
        elapsed = failed_at - started_at
        msg = f"{operation} timed out after {elapsed.total_seconds()}"
        super().__init__(msg, user, failed_at=failed_at)

    def to_slack(self) -> SlackMessage:
        """Format the exception as a Slack message.

        Returns
        -------
        safir.slack.blockkit.SlackMessage
            Slack message suitable for posting with
            `~safir.slack.webhook.SlackWebhookClient`.
        """
        started_at = format_datetime_for_logging(self.started_at)
        failed_at = format_datetime_for_logging(self.failed_at)
        fields: list[SlackBaseField] = [
            SlackTextField(heading="Started at", text=started_at),
            SlackTextField(heading="Failed at", text=failed_at),
        ]
        if self.user:
            fields.append(SlackTextField(heading="User", text=self.user))
        return SlackMessage(message=str(self), fields=fields)


class DockerRegistryError(SlackWebException):
    """An API call to a Docker Registry failed."""


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
        safir.slack.blockkit.SlackMessage
            Slack message suitable for posting as an alert.
        """
        message = super().to_slack()
        obj = f"{self.kind} {self.namespace}" if self.namespace else self.kind
        message.blocks.append(SlackTextBlock(heading="Object", text=obj))
        return message


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
        safir.slack.blockkit.SlackMessage
            Slack message suitable for posting as an alert.
        """
        message = super().to_slack()
        block = SlackCodeBlock(heading="Error", code=self.error)
        message.blocks.append(block)
        return message


class GafaelfawrWebError(SlackWebException):
    """An API call to Gafaelfawr failed."""


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
        safir.slack.blockkit.SlackMessage
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
            if self.namespace:
                obj = f"{self.kind} in namespace {self.namespace}"
            else:
                obj = self.kind
            block = SlackTextBlock(heading="Object", text=obj)
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


class LabDeletionError(SlackException):
    """An error occurred when deleting a lab.

    Currently, we don't have access to the underlying error. This will be
    fixed in future work.
    """


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
        safir.slack.blockkit.SlackMessage
            Slack message suitable for posting as an alert.
        """
        message = super().to_slack()
        if self.name:
            if self.namespace:
                obj = f"{self.kind} {self.namespace}/{self.name}"
            else:
                obj = f"{self.kind} {self.name}"
        elif self.namespace:
            obj = f"{self.kind} (namespace: {self.namespace})"
        else:
            obj = self.kind
        message.blocks.append(SlackTextBlock(heading="Object", text=obj))
        return message


class MissingSecretError(MissingObjectError):
    """Secret specified in the controller configuration was not found.

    Parameters
    ----------
    name
        Name of secret.
    namespace
        Namespace of secret.
    key
        If given, indicates the secret itself was found but the desired key
        within that secret was missing.
    """

    def __init__(
        self, name: str, namespace: str, key: str | None = None
    ) -> None:
        if key:
            message = f"No key {key} in secret {namespace}/{name}"
        else:
            message = f"Secret {namespace}/{name} does not exist"
        super().__init__(
            message, kind="Secret", namespace=namespace, name=name
        )


class NoOperationError(SlackException):
    """No operation was in progress when attempting to wait."""
