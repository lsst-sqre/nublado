"""Tests for the Gafaelfawr authenticator.

Most of the authenticator machinery is deeply entangled with JupyterHub and
therefore can't be tested easily (and is also kept as simple as possible).
This tests the logic that's sufficiently separable to run in a test harness.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from tornado import web
from tornado.httputil import HTTPHeaders

from rubin.nublado.authenticator import GafaelfawrAuthenticator
from rubin.nublado.authenticator._internals import (
    _build_auth_info,
    _GafaelfawrLoginHandler,
    _GafaelfawrLogoutHandler,
)


@pytest.mark.asyncio
async def test_authenticator() -> None:
    authenticator = GafaelfawrAuthenticator()
    assert authenticator.get_handlers(MagicMock()) == [
        ("/gafaelfawr/login", _GafaelfawrLoginHandler),
        ("/logout", _GafaelfawrLogoutHandler),
    ]

    assert authenticator.login_url("/hub") == "/hub/gafaelfawr/login"

    # No request, just return True.
    assert await authenticator.refresh_user(MagicMock()) is True
    handler = MagicMock()
    handler.request.headers = HTTPHeaders()

    # No headers, internal call, just return True and let JupyterHub do its
    # normal thing.
    assert await authenticator.refresh_user(MagicMock(), handler) is True

    # Token matches, return true.
    user = MagicMock()
    user.name = "rachel"
    user.get_auth_state = AsyncMock()
    user.get_auth_state.return_value = {"token": "token-of-affection"}
    assert await authenticator.refresh_user(user, handler) is True

    # Token doesn't match, missing header, raise an error.
    handler.request.headers = HTTPHeaders(
        {"X-Auth-Request-Token": "token-of-affection"}
    )
    user.get_auth_state.return_value = {"token": "blahblahblah"}
    with pytest.raises(web.HTTPError):
        await authenticator.refresh_user(user, handler)

    # Username doesn't match, raise an error. JupyterHub doesn't allow
    # changing usernames in an authentication refresh, so we need to punt the
    # user out entirely and force them to log in again.
    handler.request.headers = HTTPHeaders(
        {
            "X-Auth-Request-User": "rachel",
            "X-Auth-Request-Token": "token-of-affection",
        }
    )
    user.name = "wrench"
    with pytest.raises(web.HTTPError):
        await authenticator.refresh_user(user, handler)

    # Token doesn't match, proper headers, return the new auth state.
    user.name = "rachel"
    assert await authenticator.refresh_user(user, handler) == {
        "name": "rachel",
        "auth_state": {"token": "token-of-affection"},
    }


@pytest.mark.asyncio
async def test_login_handler() -> None:
    """Test the core functionality of the login handler.

    We unfortunately can't test it directly because mocking out the guts of
    Tornado and JupyterHub is too tedious and fragile. But all the important
    work happens in a helper function anyway.
    """
    with pytest.raises(web.HTTPError):
        _build_auth_info(HTTPHeaders())

    # One or the other header is missing.
    headers = HTTPHeaders({"X-Auth-Request-User": "rachel"})
    with pytest.raises(web.HTTPError):
        _build_auth_info(headers)
    headers = HTTPHeaders({"X-Auth-Request-Token": "token-of-affection"})
    with pytest.raises(web.HTTPError):
        _build_auth_info(headers)

    # Test with proper headers.
    headers = HTTPHeaders(
        {
            "X-Auth-Request-User": "rachel",
            "X-Auth-Request-Token": "token-of-affection",
        }
    )
    auth_state = _build_auth_info(headers)
    assert auth_state == {
        "name": "rachel",
        "auth_state": {"token": "token-of-affection"},
    }
