"""Test that the Slack message from a web error is correctly redacted."""

import httpx
import pytest
from safir.slack.blockkit import SlackCodeBlock, SlackTextBlock

from rubin.nublado.client.exceptions import JupyterWebError


@pytest.mark.asyncio
async def test_url_redaction() -> None:
    req = httpx.Request(
        method="GET",
        url="https://raven.poe/lenore/response_type%3Dcode%26state%3Dlost",
    )
    reason_phrase = b"Night's Plutonian shore"

    rv = """Then, methaught the air grew denser, perfumed from an unseen censer
    Swung by Seraphim whose foot-falls tinkled on the tufted floor.

    xsrf_token: "Nevermore"
    """

    resp = httpx.Response(
        status_code=404,
        content=rv.encode("utf-8"),
        text=rv,
        extensions={"reason_phrase": reason_phrase},
        request=req,
    )
    exc: httpx.HTTPError | None = None
    try:
        resp.raise_for_status()
    except httpx.HTTPError as h_exc:
        exc = h_exc
    assert isinstance(exc, httpx.HTTPError)
    web_error = JupyterWebError.from_exception(exc, user="edgar")
    slack_msg = web_error.to_slack()
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
    assert slack_msg.attachments[0].heading == "Body"
    assert slack_msg.attachments[0].code.find("Nevermore") == -1
    assert slack_msg.attachments[0].code.find("xsrf_token") != -1
    assert slack_msg.attachments[0].code.find("<redacted>") != -1
