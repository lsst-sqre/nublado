"""Test that xsrf tokens inside a message body are redacted."""

from __future__ import annotations

import pytest
from httpx import HTTPError, Request, Response

from rubin.nublado.client import NubladoClientSlackWebException


@pytest.mark.asyncio
async def test_token_redaction() -> None:
    msg = 'xsrf_token: "Nevermore"'
    req = Request(method="GET", url="https://raven.poe/")
    reason_phrase = b"Existential Ennui"
    resp = Response(
        status_code=500,
        content=msg.encode("utf-8"),
        extensions={"reason_phrase": reason_phrase},
        request=req,
        text=msg,
    )
    try:
        resp.raise_for_status()
    except HTTPError as e:
        exc = NubladoClientSlackWebException.from_exception(e)
    assert exc.body is not None
    assert exc.body.find("Nevermore") == -1
    assert exc.body.find("<redacted>") != -1
