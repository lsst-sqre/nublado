"""Test that OAuth state inside a URL is redacted."""

import httpx
import pytest

from rubin.nublado.client.exceptions import JupyterWebError


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
    exc: httpx.HTTPError | None = None
    try:
        resp.raise_for_status()
    except httpx.HTTPError as h_exc:
        exc = h_exc
    assert isinstance(exc, httpx.HTTPError)
    web_error = JupyterWebError.from_exception(exc, user="edgar")
    assert web_error.url is not None
    assert web_error.url.find("lost") == -1
    assert web_error.url.find("<redacted>") != -1
