"""Tests for exceptions."""

import datetime

from anys import AnyContains
from safir.datetime import format_datetime_for_logging

from controller.exceptions import (
    ControllerTimeoutError,
    DuplicateObjectError,
    KubernetesError,
    MissingObjectError,
)


def test_controller_timeout_error_slack() -> None:
    started_at = datetime.datetime(2001, 11, 30, tzinfo=datetime.UTC)
    failed_at = datetime.datetime(2001, 12, 30, tzinfo=datetime.UTC)

    error = ControllerTimeoutError(
        operation="whatever",
        user="whomever",
        started_at=started_at,
        failed_at=failed_at,
    )

    slack = error.to_slack().to_slack()
    assert slack == {
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "whatever timed out after 2592000.0",
                    "verbatim": True,
                },
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": "*Started at*\n2001-11-30 00:00:00",
                        "verbatim": True,
                    },
                    {
                        "type": "mrkdwn",
                        "text": "*Failed at*\n2001-12-30 00:00:00",
                        "verbatim": True,
                    },
                    {
                        "type": "mrkdwn",
                        "text": "*User*\nwhomever",
                        "verbatim": True,
                    },
                ],
            },
            {"type": "divider"},
        ]
    }


def test_controller_timeout_error_sentry() -> None:
    started_at = datetime.datetime(2001, 11, 30, tzinfo=datetime.UTC)
    failed_at = datetime.datetime(2001, 12, 30, tzinfo=datetime.UTC)

    error = ControllerTimeoutError(
        operation="whatever",
        user="whomever",
        started_at=started_at,
        failed_at=failed_at,
    )

    sentry = error.to_sentry()
    assert sentry.username == "whomever"
    assert sentry.contexts["info"]["started_at"] == (
        format_datetime_for_logging(started_at)
    )


def test_duplicate_object_error_slack() -> None:
    error = DuplicateObjectError(
        message="whatever",
        user="whomever",
        kind="kind",
        namespace="namespace",
    )

    slack = error.to_slack().to_slack()

    assert slack == {
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "whatever",
                    "verbatim": True,
                },
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": "*Exception type*\nDuplicateObjectError",
                        "verbatim": True,
                    },
                    {
                        "type": "mrkdwn",
                        "text": AnyContains("*Failed at*"),
                        "verbatim": True,
                    },
                    {
                        "type": "mrkdwn",
                        "text": "*User*\nwhomever",
                        "verbatim": True,
                    },
                ],
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Object*\nkind namespace",
                    "verbatim": True,
                },
            },
            {"type": "divider"},
        ]
    }


def test_duplicate_object_error_sentry() -> None:
    error = DuplicateObjectError(
        message="whatever",
        user="whomever",
        kind="kind",
        namespace="namespace",
    )

    sentry = error.to_sentry()

    assert sentry.username == "whomever"
    assert sentry.tags["kind"] == "kind"
    assert sentry.tags["namespace"] == "namespace"


def test_kubernetes_error_slack() -> None:
    error = KubernetesError(
        message="whatever",
        user="whomever",
        kind="kind",
        namespace="namespace",
        name="name",
        status=503,
        body="Some response body",
    )

    slack = error.to_slack().to_slack()

    assert slack == {
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "whatever (kind namespace/name, status 503)",
                    "verbatim": True,
                },
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": "*Exception type*\nKubernetesError",
                        "verbatim": True,
                    },
                    {
                        "type": "mrkdwn",
                        "text": AnyContains("*Failed at*"),
                        "verbatim": True,
                    },
                    {
                        "type": "mrkdwn",
                        "text": "*User*\nwhomever",
                        "verbatim": True,
                    },
                    {
                        "type": "mrkdwn",
                        "text": "*Status*\n503",
                        "verbatim": True,
                    },
                ],
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Object*\nkind namespace/name",
                    "verbatim": True,
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Error*\n```\nSome response body\n```",
                    "verbatim": True,
                },
            },
            {"type": "divider"},
        ]
    }


def test_kubernetes_error_sentry() -> None:
    error = KubernetesError(
        message="whatever",
        user="whomever",
        kind="kind",
        namespace="namespace",
        name="name",
        status=503,
        body="Some response body",
    )

    sentry = error.to_sentry()

    assert sentry.username == "whomever"
    assert sentry.tags["status"] == "503"
    assert sentry.tags["name"] == "name"
    assert sentry.tags["kind"] == "kind"
    assert sentry.tags["namespace"] == "namespace"
    assert sentry.attachments["body"] == "Some response body"


def test_missing_object_error_slack() -> None:
    error = MissingObjectError(
        message="whatever",
        user="whomever",
        kind="kind",
        namespace="namespace",
        name="name",
    )

    slack = error.to_slack().to_slack()

    assert slack == {
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "whatever",
                    "verbatim": True,
                },
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": "*Exception type*\nMissingObjectError",
                        "verbatim": True,
                    },
                    {
                        "type": "mrkdwn",
                        "text": AnyContains("*Failed at*"),
                        "verbatim": True,
                    },
                    {
                        "type": "mrkdwn",
                        "text": "*User*\nwhomever",
                        "verbatim": True,
                    },
                ],
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Object*\nkind namespace/name",
                    "verbatim": True,
                },
            },
            {"type": "divider"},
        ]
    }


def test_missing_object_error_sentry() -> None:
    error = MissingObjectError(
        message="whatever",
        user="whomever",
        kind="kind",
        namespace="namespace",
        name="name",
    )

    sentry = error.to_sentry()

    assert sentry.username == "whomever"
    assert sentry.tags["kind"] == "kind"
    assert sentry.tags["name"] == "name"
    assert sentry.tags["namespace"] == "namespace"
