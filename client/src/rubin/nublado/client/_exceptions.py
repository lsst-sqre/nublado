"""Exceptions for rubin.nublado.client."""

from __future__ import annotations

import datetime
import re
from typing import Self, override

from safir.datetime import format_datetime_for_logging
from safir.slack.blockkit import (
    SlackBaseBlock,
    SlackBaseField,
    SlackCodeBlock,
    SlackException,
    SlackMessage,
    SlackTextBlock,
    SlackTextField,
    SlackWebException,
)
from safir.slack.sentry import SentryEventInfo
from websockets.exceptions import InvalidStatus, WebSocketException

from ._models import CodeContext

_ANSI_REGEX = re.compile(r"(?:\x1B[@-_]|[\x80-\x9F])[0-?]*[ -/]*[@-~]")
"""Regex that matches ANSI escape sequences."""

_TOKEN_REGEX = re.compile(r'(?i:xsrf_token:\s*"(.*)")')
"""Regex that matches XSRF tokens.

This matches the embedding we've observed, where the key is not quoted but the
value is.
"""

_OAUTH_STATE_REGEX = re.compile(r"(?im:response_type%3Dcode%26state%3D(.*))")
"""Regex that matches OAuth code states.  Will match further parameters too
but we don't really care."""

__all__ = [
    "NubladoDiscoveryError",
    "NubladoError",
    "NubladoExecutionError",
    "NubladoProtocolError",
    "NubladoRedirectError",
    "NubladoSpawnError",
    "NubladoTimeoutError",
    "NubladoWebError",
    "NubladoWebSocketError",
]


def _remove_ansi_escapes(string: str) -> str:
    """Remove ANSI escape sequences from a string.

    Jupyter labs like to format error messages with lots of ANSI escape
    sequences, and Slack doesn't like that in messages (nor do humans want to
    see them). Strip them out.

    Based on `this StackOverflow answer
    <https://stackoverflow.com/questions/14693701/>`__.

    Parameters
    ----------
    string
        String to strip ANSI escapes from.

    Returns
    -------
    str
        Sanitized string.
    """
    return _ANSI_REGEX.sub("", string)


def _sanitize_body(body: str | None) -> str:
    """Attempt to scrub XSRF token from HTTP response body."""
    if not body:
        return ""
    tok_match = _TOKEN_REGEX.search(body)
    if not tok_match:
        return body
    return re.sub(tok_match.group(1), "<redacted>", body)


def _sanitize_url(url: str | None) -> str:
    """Attempt to scrub OAuth state code from URL."""
    if not url:
        return ""
    url_match = _OAUTH_STATE_REGEX.search(url)
    if not url_match:
        return url
    return re.sub(url_match.group(1), "<redacted>", url)


class NubladoError(SlackException):
    """A Nublado client error.

    This adds some additional fields to `~safir.slack.blockkit.SlackException`
    but is otherwise equivalent. It is intended to be subclassed. Subclasses
    must override the `to_slack` and `to_sentry` methods.

    Parameters
    ----------
    message
        Exception message.
    user
        User Nublado client was acting on behalf of.
    context
        The code context for this operation, if any.
    failed_at
        When the operation failed. Omit to use the current time.
    started_at
        When the operation that failed began.

    Attributes
    ----------
    context
        The code context for this operation, if any.
    failed_at
        When the operation failed.
    started_at
        When the operation that ended in an exception started.
    user
        User Nublado client was acting on behalf of.
    """

    def __init__(
        self,
        message: str,
        user: str | None = None,
        *,
        context: CodeContext | None = None,
        failed_at: datetime.datetime | None = None,
        started_at: datetime.datetime | None = None,
    ) -> None:
        super().__init__(message, user, failed_at=failed_at)
        self.started_at = started_at
        self.context = context if context else CodeContext()

    @override
    def to_sentry(self) -> SentryEventInfo:
        """Return an object with tags and contexts to add to Sentry events.

        Returns
        -------
        `~safir.slack.blockkit.SentryEventInfo`
            Annotated Sentry object.
        """
        info = super().to_sentry()
        if image := self.context.image:
            info.tags["image"] = image
        if self.context.node:
            info.tags["node"] = self.context.node
        if self.context.notebook:
            info.tags["notebook"] = self.context.notebook
        if self.context.cell:
            info.tags["cell"] = self.context.cell
        if self.context.cell_number:
            info.tags["cell_number"] = self.context.cell_number

        if self.started_at:
            context = info.contexts.setdefault("info", {})
            started_at = format_datetime_for_logging(self.started_at)
            context["started_at"] = started_at

        return info

    @override
    def to_slack(self) -> SlackMessage:
        """Format the error as a Slack Block Kit message.

        Returns
        -------
        `~safir.slack.blockkit.SlackMessage`
            Formatted Slack message.
        """
        return SlackMessage(
            message=self.message,
            blocks=self._build_slack_blocks(),
            fields=self._build_slack_fields(),
        )

    def _build_slack_blocks(self) -> list[SlackBaseBlock]:
        """Return common blocks to put in any alert.

        Returns
        -------
        list of safir.slack.blockkit.SlackBaseBlock
            Common blocks to add to the Slack message.
        """
        blocks: list[SlackBaseBlock] = []
        if node := self.context.node:
            blocks.append(SlackTextBlock(heading="Node", text=node))
        if notebook := self.context.notebook:
            if self.context.cell:
                text = f"`{notebook}` cell `{self.context.cell}`"
                if self.context.cell_number:
                    text += f" ({self.context.cell_number})"
                blocks.append(SlackTextBlock(heading="Cell", text=text))
            else:
                block = SlackTextBlock(heading="Notebook", text=notebook)
                blocks.append(block)
        elif self.context.cell:
            text = self.context.cell
            if self.context.cell_number:
                text += " ({self.context.cell_number})"
            blocks.append(SlackTextBlock(heading="Cell", text=text))
        return blocks

    def _build_slack_fields(self) -> list[SlackBaseField]:
        """Return common fields to put in any alert.

        Returns
        -------
        list of safir.slack.blockkit.SlackBaseField
            Common fields to add to the Slack message.
        """
        failed_at = format_datetime_for_logging(self.failed_at)
        fields: list[SlackBaseField] = [
            SlackTextField(heading="Failed at", text=failed_at),
            SlackTextField(heading="Exception type", text=type(self).__name__),
        ]
        if self.started_at:
            started_at = format_datetime_for_logging(self.started_at)
            field = SlackTextField(heading="Started at", text=started_at)
            fields.insert(0, field)
        if self.user:
            fields.append(SlackTextField(heading="User", text=self.user))
        if image := self.context.image:
            fields.append(SlackTextField(heading="Image", text=image))
        return fields


class NubladoDiscoveryError(NubladoError):
    """Error finding a required service in service discovery."""


class NubladoExecutionError(NubladoError):
    """Error generated by code execution in a notebook on JupyterLab.

    Parameters
    ----------
    user
        User mobu was operating as when the exception happened.
    code
        Python code that failed execution.
    context
        The code context for this operation, if any.
    error
        Error result from the code execution (usually a traceback).
    failed_at
        When the operation failed. Omit to use the current time.
    status
        JupyterLab execution status from the WebSocket message.
    started_at
        When the operation that failed began.

    Attributes
    ----------
    context
        The code context for this operation, if any.
    code
        Python code that failed execution.
    error
        Error result from the code execution (usually a traceback).
    failed_at
        When the operation failed.
    started_at
        When the operation that ended in an exception started.
    status
        JupyterLab execution status from the WebSocket message.
    user
        User Nublado client was acting on behalf of.
    """

    def __init__(
        self,
        user: str,
        *,
        code: str | None = None,
        context: CodeContext | None = None,
        error: str | None = None,
        failed_at: datetime.datetime | None = None,
        status: str | None = None,
        started_at: datetime.datetime | None = None,
    ) -> None:
        super().__init__(
            "Code execution failed",
            user,
            started_at=started_at,
            failed_at=failed_at,
            context=context,
        )
        self.code = code
        self.error = error
        self.status = status

    @override
    def __str__(self) -> str:
        if notebook := self.context.notebook:
            if cell := self.context.cell:
                msg = f"{self.user}: cell {cell} of notebook {notebook} failed"
            else:
                msg = f"{self.user}: cell of notebook {notebook} failed"
            if self.status:
                msg += f" (status: {self.status})"
            if self.code:
                msg += f"\nCode: {self.code}"
        elif self.code:
            msg = f"{self.user}: running code '{self.code}' failed"
        else:
            msg = f"{self.user}: running code failed"
        if self.error:
            msg += f"\nError: {_remove_ansi_escapes(self.error)}"
        return msg

    @override
    def to_sentry(self) -> SentryEventInfo:
        info = super().to_sentry()
        if self.status:
            info.tags["status"] = self.status
        if self.error:
            error = _remove_ansi_escapes(self.error)
            info.attachments["nublado_error.txt"] = error
        if self.code:
            info.attachments["nublado_code.txt"] = self.code
        return info

    @override
    def to_slack(self) -> SlackMessage:
        message = super().to_slack()
        if self.context.notebook:
            intro = f"Error while running `{self.context.notebook}`"
            if self.context.cell:
                intro += f" cell `{self.context.cell}`"
        else:
            intro = "Error while running code"
        if self.status:
            intro += f" (status: {self.status})"
        message.message = intro

        if self.error:
            error = _remove_ansi_escapes(self.error)
            attachment = SlackCodeBlock(heading="Error", code=error)
            message.attachments.append(attachment)
        if code := self.code:
            attachment = SlackCodeBlock(heading="Code executed", code=code)
            message.attachments.append(attachment)

        return message


class NubladoProtocolError(NubladoError):
    """Unexpected response from JupyterHub or JupyterLab."""


class NubladoRedirectError(NubladoError):
    """Loop or unexpected redirect outside of the Nublado URL space.

    Parameters
    ----------
    message
        Exception message.
    user
        User Nublado client was acting on behalf of.
    context
        The code context for this operation, if any.
    failed_at
        When the operation failed. Omit to use the current time.
    started_at
        When the operation that failed began.
    url
        URL at which the redirect loop was detected.

    Attributes
    ----------
    context
        The code context for this operation, if any.
    failed_at
        When the operation failed.
    started_at
        When the operation that ended in an exception started.
    url
        URL at which the redirect loop was detected.
    user
        User Nublado client was acting on behalf of.
    """

    def __init__(
        self,
        message: str,
        url: str,
        user: str | None = None,
        *,
        context: CodeContext | None = None,
        failed_at: datetime.datetime | None = None,
        started_at: datetime.datetime | None = None,
    ) -> None:
        super().__init__(
            f"{message}: {_sanitize_url(url)}",
            user,
            context=context,
            failed_at=failed_at,
            started_at=started_at,
        )
        self.url = _sanitize_url(url)

    @override
    def to_sentry(self) -> SentryEventInfo:
        info = super().to_sentry()
        info.tags["httpx_request_method"] = "GET"
        info.tags["httpx_request_url"] = self.url
        return info

    @override
    def to_slack(self) -> SlackMessage:
        message = super().to_slack()
        text = f"GET {self.url}"
        message.blocks.append(SlackTextBlock(heading="URL", text=text))
        return message


class NubladoSpawnError(NubladoError):
    """Nublado failed to spawn the requested JupyterLab instance.

    Parameters
    ----------
    message
        Exception message.
    log
        Log messages from the Nublado spawn.
    user
        User Nublado client was acting on behalf of.
    context
        The code context for this operation, if any.
    failed_at
        When the operation failed. Omit to use the current time.
    started_at
        When the operation that failed began.

    Attributes
    ----------
    context
        The code context for this operation, if any.
    failed_at
        When the operation failed.
    log
        Log messages from the Nublado spawn.
    started_at
        When the operation that ended in an exception started.
    user
        User Nublado client was acting on behalf of.
    """

    def __init__(
        self,
        message: str,
        log: list[str],
        user: str | None = None,
        *,
        context: CodeContext | None = None,
        failed_at: datetime.datetime | None = None,
        started_at: datetime.datetime | None = None,
    ) -> None:
        super().__init__(
            message,
            user,
            context=context,
            failed_at=failed_at,
            started_at=started_at,
        )
        self.log = log

    @override
    def to_sentry(self) -> SentryEventInfo:
        info = super().to_sentry()
        log = "\n".join(_remove_ansi_escapes(m) for m in self.log)
        info.attachments["spawn_log.txt"] = log
        return info

    @override
    def to_slack(self) -> SlackMessage:
        message = super().to_slack()
        log = "\n".join(_remove_ansi_escapes(m) for m in self.log)
        attachment = SlackCodeBlock(heading="Spawn log", code=log)
        message.attachments.append(attachment)
        return message


class NubladoTimeoutError(NubladoError):
    """Timed out opening or waiting for WebSocket messages."""


class NubladoWebError(SlackWebException, NubladoError):
    """Represents an exception that can be reported to Slack.

    Similar to `NubladoError`, this adds some additional fields to
    `~safir.slack.blockkit.SlackWebException` but is otherwise equivalent. It
    is intended to be subclassed. Subclasses may want to override the
    `to_slack` and `to_sentry` methods.

    Parameters
    ----------
    message
        Exception string value, which is the default Slack message.
    user
        Username on whose behalf the request is being made.
    body
        Body of failure message, if any.
    context
        The code context for this operation, if any.
    failed_at
        When the exception happened. Omit to use the current time.
    method
        Method of request.
    started_at
        When the operation that failed began.
    status
        Status code of failure, if any.
    url
        URL of the request.

    Attributes
    ----------
    message
        Exception string value, which is the default Slack message.
    body
        Body of failure message, if any.
    context
        The code context for this operation, if any.
    failed_at
        When the exception happened. Omit to use the current time.
    method
        Method of request.
    started_at
        When the operation that failed began.
    status
        Status code of failure, if any.
    url
        URL of the request.
    user
        Username on whose behalf the request is being made.
    """

    def __init__(
        self,
        message: str,
        user: str | None = None,
        *,
        body: str | None = None,
        context: CodeContext | None = None,
        failed_at: datetime.datetime | None = None,
        method: str | None = None,
        started_at: datetime.datetime | None = None,
        status: int | None = None,
        url: str | None = None,
    ) -> None:
        super().__init__(
            message,
            user=user,
            failed_at=failed_at,
            method=method,
            url=_sanitize_url(url) if url else None,
            status=status,
            body=_sanitize_body(body) if body else None,
        )
        self.started_at = started_at
        self.context = context if context else CodeContext()

    @override
    def to_sentry(self) -> SentryEventInfo:
        """Format the error as a Slack Block Kit message.

        Returns
        -------
        `~safir.slack.blockkit.SlackMessage`
            Formatted Slack message.
        """
        info = NubladoError.to_sentry(self)
        web_info = super().to_sentry()
        info.tags.update(web_info.tags)
        info.contexts.update(web_info.contexts)
        info.attachments.update(web_info.attachments)
        return info

    @override
    def to_slack(self) -> SlackMessage:
        """Return an object with tags and contexts to add to Sentry events.

        Returns
        -------
        `~safir.slack.blockkit.SentryEventInfo`
            Annotated Sentry object.
        """
        message = NubladoError.to_slack(self)
        message.message = _sanitize_url(message.message)
        if self.url:
            text = f"{self.method} {self.url}" if self.method else self.url
            message.blocks.append(SlackTextBlock(heading="URL", text=text))
        if self.body:
            block = SlackCodeBlock(heading="Response", code=self.body)
            message.attachments.append(block)
        return message


class NubladoWebSocketError(NubladoError):
    """An error occurred talking to the Jupyter lab WebSocket.

    Parameters
    ----------
    message
        Exception string value, which is the default Slack message.
    user
        Username on whose behalf the request is being made.
    body
        Body of failure message, if any.
    code
        WebSocket status code of failure, if any.
    context
        The code context for this operation, if any.
    failed_at
        When the exception happened. Omit to use the current time.
    started_at
        When the operation that failed began.

    Attributes
    ----------
    message
        Exception string value, which is the default Slack message.
    user
        Username on whose behalf the request is being made.
    body
        Body of failure message, if any.
    code
        WebSocket status code of failure, if any.
    context
        The code context for this operation, if any.
    failed_at
        When the exception happened. Omit to use the current time.
    started_at
        When the operation that failed began.
    """

    @classmethod
    def from_exception(cls, exc: WebSocketException, user: str) -> Self:
        """Convert from a `~websockets.exceptions.WebSocketException`.

        Parameters
        ----------
        exc
            Underlying exception.
        user
            User the code is running as.

        Returns
        -------
        NubladoWebSocketError
            Newly-created exception.
        """
        if str(exc):
            error = f"{type(exc).__name__}: {exc!s}"
        else:
            error = type(exc).__name__
        if isinstance(exc, InvalidStatus):
            return cls(
                f"JupyterLab WebSocket unexpectedly closed: {error}",
                user=user,
                body=exc.response.body.decode() if exc.response.body else None,
                code=exc.response.status_code,
            )
        else:
            return cls(f"Error talking to lab WebSocket: {error}", user)

    def __init__(
        self,
        message: str,
        user: str,
        *,
        body: str | None = None,
        code: int | None = None,
        context: CodeContext | None = None,
        failed_at: datetime.datetime | None = None,
        started_at: datetime.datetime | None = None,
    ) -> None:
        super().__init__(
            message,
            user,
            started_at=started_at,
            failed_at=failed_at,
            context=context,
        )
        self.code = code
        self.body = _sanitize_body(body)

    @override
    def to_sentry(self) -> SentryEventInfo:
        info = super().to_sentry()
        if self.code:
            info.tags["code"] = str(self.code)
        if self.body:
            info.attachments["body.txt"] = self.body
        return info

    @override
    def to_slack(self) -> SlackMessage:
        message = super().to_slack()
        if self.code:
            field = SlackTextField(heading="Code", text=str(self.code))
            message.fields.append(field)
        if self.body:
            block = SlackTextBlock(heading="Body", text=self.body)
            message.attachments.append(block)
        return message
