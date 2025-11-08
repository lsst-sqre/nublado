"""Test that the Slack message from a web error is correctly redacted."""

from __future__ import annotations

import pytest
from httpx import HTTPError, Request, Response
from safir.slack.blockkit import SlackCodeBlock, SlackTextBlock

from rubin.nublado.client import NubladoWebError


@pytest.mark.asyncio
async def test_url_redaction() -> None:
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
        content=body.encode("utf-8"),
        text=body,
        extensions={"reason_phrase": b"Night's Plutonian shore"},
        request=request,
    )
    try:
        response.raise_for_status()
    except HTTPError as e:
        exc = NubladoWebError.from_exception(e, user="edgar")

    slack_msg = exc.to_slack()
    assert slack_msg.message.find("lost") == -1
    assert slack_msg.message.find("<redacted>") != -1
    assert len(slack_msg.blocks) == 1
    assert isinstance(slack_msg.blocks[0], SlackTextBlock)
    assert slack_msg.blocks[0].heading == "URL"
    assert slack_msg.blocks[0].text.find("lost") == -1
    assert slack_msg.blocks[0].text.find("state") != -1
    assert slack_msg.blocks[0].text.find("<redacted>") != -1
    assert len(slack_msg.attachments) == 1
    assert isinstance(slack_msg.attachments[0], SlackCodeBlock)
    assert slack_msg.attachments[0].heading == "Response"
    assert slack_msg.attachments[0].code.find("Nevermore") == -1
    assert slack_msg.attachments[0].code.find("xsrf_token") != -1
    assert slack_msg.attachments[0].code.find("<redacted>") != -1
