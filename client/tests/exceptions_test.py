"""Test exception classes for the Nublado client."""

from __future__ import annotations

from httpx import HTTPError, Request, Response
from safir.slack.blockkit import SlackCodeBlock, SlackTextBlock

from rubin.nublado.client import NubladoWebError


def test_filtering_body() -> None:
    body = 'xsrf_token: "Nevermore"'
    response = Response(
        status_code=500,
        content=body.encode(),
        extensions={"reason_phrase": b"Existential Ennui"},
        request=Request(method="GET", url="https://raven.poe/"),
        text=body,
    )
    try:
        response.raise_for_status()
    except HTTPError as e:
        exc = NubladoWebError.from_exception(e)
    assert exc.body
    assert "Nevermore" not in exc.body
    assert "<redacted>" in exc.body


def test_filtering_url_body() -> None:
    request = Request(
        method="GET",
        url="https://raven.poe/lenore/response_type%3Dcode%26state%3Dlost",
    )
    body = (
        "Then, methaught the air grew denser, perfumed from an unseen censer,"
        "\nSwung by Seraphim whose foot-falls tinkled on the tufted floor."
        '\n\nxsrf_token: "Nevermore"'
    )
    response = Response(
        status_code=404,
        content=body.encode(),
        text=body,
        extensions={"reason_phrase": b"Night's Plutonian shore"},
        request=request,
    )
    try:
        response.raise_for_status()
    except HTTPError as e:
        exc = NubladoWebError.from_exception(e, user="edgar")

    assert exc.url
    assert "lost" not in exc.url
    assert "<redacted>" in exc.url

    message = exc.to_slack()
    assert "lost" not in message.message
    assert "<redacted>" in message.message
    assert len(message.blocks) == 1
    assert isinstance(message.blocks[0], SlackTextBlock)
    assert message.blocks[0].heading == "URL"
    assert "lost" not in message.blocks[0].text
    assert "state" in message.blocks[0].text
    assert "<redacted>" in message.blocks[0].text
    assert len(message.attachments) == 1
    assert isinstance(message.attachments[0], SlackCodeBlock)
    assert message.attachments[0].heading == "Response"
    assert "Nevermore" not in message.attachments[0].code
    assert "xsrf_token" in message.attachments[0].code
    assert "<redacted>" in message.attachments[0].code
