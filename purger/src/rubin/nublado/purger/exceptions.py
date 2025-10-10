"""Exceptions for the purger."""

from typing import override

from safir.slack.blockkit import SlackException, SlackMessage, SlackTextBlock
from safir.slack.sentry import SentryEventInfo

__all__ = ["NotLockedError", "PlanNotReadyError", "PurgeFailedError"]


class PlanNotReadyError(SlackException):
    """An operation needing a Plan was requested, but no Plan is ready."""


class NotLockedError(SlackException):
    """An operation requiring a lock was requested with no lock held."""


class PurgeFailedError(SlackException):
    """A purge encountered errors."""

    def __init__(self, message: str, failed_files: dict[str, str]) -> None:
        super().__init__(message)
        self.failed_files = failed_files
        self.report = ", ".join(
            [f"{x!s}: {self.failed_files[x]!s}" for x in self.failed_files]
        )

    @override
    def to_slack(self) -> SlackMessage:
        """Format this exception as a slack message."""
        message = super().to_slack()
        attachment = SlackTextBlock(heading="Failed Files", text=self.report)
        message.attachments.append(attachment)
        return message

    @override
    def to_sentry(self) -> SentryEventInfo:
        """Return Sentry metadata for this exception."""
        info = super().to_sentry()
        info.contexts["failed_files"] = self.failed_files
        return info
