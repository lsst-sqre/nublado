"""Exceptions for the purger."""

from safir.slack.blockkit import SlackException


class PlanNotReadyError(SlackException):
    """An operation needing a Plan was requested, but no Plan is ready."""


class NotLockedError(SlackException):
    """An operation requiring a lock was requested with no lock held."""
