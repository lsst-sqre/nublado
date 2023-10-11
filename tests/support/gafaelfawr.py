"""Mock responses from Gafaelfawr."""

from __future__ import annotations

import respx
from httpx import Request, Response

from jupyterlabcontroller.models.domain.gafaelfawr import (
    GafaelfawrUser,
    GafaelfawrUserInfo,
)

__all__ = ["MockGafaelfawr", "register_mock_gafaelfawr"]


class MockGafaelfawr:
    """Mock Gafaelfawr that returns preconfigured test information.

    Parameters
    ----------
    tokens
        Dictionary of tokens to mock user information. The first token and
        user in the dictionary is returned by `get_test_token_and_user` as the
        default token and user to use in tests.
    """

    def __init__(self, tokens: dict[str, GafaelfawrUserInfo]) -> None:
        self._tokens = tokens

    def get_info(self, request: Request) -> Response:
        """Mock user information response.

        Parameters
        ----------
        request
            Incoming request.

        Returns
        -------
        httpx.Response
            Returns 200 with the details if the token was found, otherwise
            403 if the token is invalid.
        """
        authorization = request.headers["Authorization"]
        auth_type, token = authorization.split(None, 1)
        assert auth_type.lower() == "bearer"
        if token in self._tokens:
            return Response(200, json=self._tokens[token].model_dump())
        else:
            return Response(403)

    def get_test_user(self) -> GafaelfawrUser:
        """Get a token for tests."""
        token, user = next(iter(self._tokens.items()))
        return GafaelfawrUser(token=token, **user.model_dump())


def register_mock_gafaelfawr(
    respx_mock: respx.Router,
    base_url: str,
    tokens: dict[str, GafaelfawrUserInfo],
) -> MockGafaelfawr:
    """Mock out Gafaelfawr.

    Parameters
    ----------
    respx_mock
        Mock router.
    base_url
        Base URL on which the mock API should appear to listen.
    tokens
        Mock user information.

    Returns
    -------
    MockGafaelfawr
        Mock Gafaelfawr API object.
    """
    mock = MockGafaelfawr(tokens)
    api_url = f"{base_url}/auth/api/v1/user-info"
    respx_mock.get(api_url).mock(side_effect=mock.get_info)
    return mock
