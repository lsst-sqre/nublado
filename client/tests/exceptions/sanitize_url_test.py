"""Test that OAuth state inside a URL is redacted."""

import httpx
import pytest

from rubin.nublado.client import NubladoWebError


@pytest.mark.asyncio
async def test_url_redaction() -> None:
    req = httpx.Request(
        method="GET",
        url="https://raven.poe/lenore/response_type%3Dcode%26state%3Dlost",
    )
    reason_phrase = b"Night's Plutonian shore"
    resp = httpx.Response(
        status_code=404,
        extensions={"reason_phrase": reason_phrase},
        request=req,
    )
    try:
        resp.raise_for_status()
    except httpx.HTTPError as e:
        exc = NubladoWebError.from_exception(e, user="edgar")
    assert exc.url is not None
    assert exc.url.find("lost") == -1
    assert exc.url.find("<redacted>") != -1
