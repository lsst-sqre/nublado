"""Mock responses from Gafaelfawr.  Time to lift this into safir or import
directly from Gafaelfawr.

Ideally, these should use the same models Gafaelfawr itself uses. Until that's
possible via a PyPI library, these models are largely copied from Gafaelfawr.
"""

from __future__ import annotations

import json
from urllib.parse import urljoin

import respx
from httpx import Request, Response
from pydantic import BaseModel, Field

__all__ = [
    "MockGafaelfawr",
    "register_mock_gafaelfawr",
    "GafaelfawrUserInfo",
    "GafaelfawrUser",
]

### Models

GROUPNAME_REGEX = "^[a-zA-Z][a-zA-Z0-9._-]*$"
"""Regex matching all valid group names."""

USERNAME_REGEX = (
    "^[a-z0-9](?:[a-z0-9]|-[a-z0-9])*[a-z](?:[a-z0-9]|-[a-z0-9])*$"
)


class UserGroup(BaseModel):
    """Gafaelfawr's representation of a single group."""

    name: str = Field(
        ...,
        examples=["ferrymen"],
        title="Group to which lab user belongs",
        description="Should follow Unix naming conventions",
        pattern=GROUPNAME_REGEX,
    )

    id: int | None = Field(
        None,
        examples=[2023],
        title="Numeric GID of the group (POSIX)",
        description="32-bit unsigned integer",
    )


class NotebookQuota(BaseModel):
    """Notebook Aspect quota information for a user."""

    cpu: float = Field(..., title="CPU equivalents", examples=[4.0])

    memory: float = Field(
        ..., title="Maximum memory use (GiB)", examples=[16.0]
    )

    @property
    def memory_bytes(self) -> int:
        """Maximum memory use in bytes."""
        return int(self.memory * 1024 * 1024 * 1024)


class UserQuota(BaseModel):
    """Quota information for a user."""

    api: dict[str, int] = Field(
        {},
        title="API quotas",
        description=(
            "Mapping of service names to allowed requests per 15 minutes."
        ),
        examples=[
            {
                "datalinker": 500,
                "hips": 2000,
                "tap": 500,
                "vo-cutouts": 100,
            }
        ],
    )

    notebook: NotebookQuota | None = Field(
        None, title="Notebook Aspect quotas"
    )


class GafaelfawrUserInfo(BaseModel):
    """User metadata from Gafaelfawr."""

    username: str = Field(
        ...,
        examples=["ribbon"],
        title="Username for Lab user",
        pattern=USERNAME_REGEX,
    )

    name: str | None = Field(
        None,
        examples=["Ribbon"],
        title="Human-friendly display name for user",
        description=(
            "May contain spaces, capital letters, and non-ASCII characters."
            " Should be the user's preferred representation of their name to"
            " other humans."
        ),
    )

    uid: int = Field(
        ...,
        examples=[1104],
        title="Numeric UID for user (POSIX)",
        description="32-bit unsigned integer",
    )

    gid: int = Field(
        ...,
        examples=[1104],
        title="Numeric GID for user's primary group (POSIX)",
        description="32-bit unsigned integer",
    )

    groups: list[UserGroup] = Field([], title="User's group memberships")

    quota: UserQuota | None = Field(None, title="User's quotas")

    @property
    def supplemental_groups(self) -> list[int]:
        """Supplemental GIDs."""
        return [g.id for g in self.groups if g.id]

    def groups_json(self) -> str:
        """Group membership serialized to JSON.

        Groups without GIDs are omitted since we can't do anything with them
        in the context of a user lab.
        """
        return json.dumps([g.model_dump() for g in self.groups if g.id])


class GafaelfawrUser(GafaelfawrUserInfo):
    """User information from Gafaelfawr supplemented with the user's token.

    This model is used to pass the user information around internally,
    bundling the user's metadata with their notebook token.
    """

    token: str = Field(..., title="Notebook token")

    def to_headers(self) -> dict[str, str]:
        """Return the representation of this user as HTTP request headers.

        Used primarily by the test suite for constructing authenticated
        requests from a user.
        """
        return {
            "X-Auth-Request-Token": self.token,
            "X-Auth-Request-User": self.username,
        }


class GafaelfawrTokenInfo(BaseModel):
    """Minimalist representation of a token with scopes."""

    token: str = Field(..., title="Notebook token")

    scopes: list[str] = Field(..., title="Token scopes")


### Mocks


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

    def get_token(self, request: Request) -> Response:
        """Mock token information response.

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
            g_token = GafaelfawrTokenInfo(
                token=token,
                scopes=["exec:notebook", "exec:portal", "read:tap"],
            )
            return Response(200, json=g_token.model_dump())
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
    user_url = urljoin(base_url, "/auth/api/v1/user-info")
    token_url = urljoin(base_url, "/auth/api/v1/token-info")
    respx_mock.get(user_url).mock(side_effect=mock.get_info)
    respx_mock.get(token_url).mock(side_effect=mock.get_token)
    return mock
