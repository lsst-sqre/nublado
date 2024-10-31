"""Test that xsrf tokens inside a message body are redacted."""

import httpx
import pytest

from rubin.nublado.client.exceptions import ExecutionAPIError


@pytest.mark.asyncio
async def test_token_redaction() -> None:
    msg = 'xsrf_token: "Nevermore"'
    req = httpx.Request(method="GET", url="https://raven.poe/")
    reason_phrase = b"Existential Ennui"
    resp = httpx.Response(
        status_code=500,
        content=msg.encode("utf-8"),
        extensions={"reason_phrase": reason_phrase},
        request=req,
        text=msg,
    )
    exc = ExecutionAPIError.from_response("edgar", resp)
    assert exc.msg is not None
    assert exc.msg.find("Nevermore") == -1
    assert exc.msg.find("<redacted>") != -1
