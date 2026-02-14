"""Mock responses from Gafaelfawr."""

from __future__ import annotations

from rubin.gafaelfawr import GafaelfawrUserInfo, MockGafaelfawr

from nublado.controller.models.domain.gafaelfawr import GafaelfawrUser

from .data import NubladoData

__all__ = [
    "GafaelfawrTestUser",
    "create_gafaelfawr_user",
]


class GafaelfawrTestUser(GafaelfawrUser):
    """Gafaelfawr user with token and methods useful for tests."""

    def to_test_headers(self) -> dict[str, str]:
        """Return the representation of this user as HTTP request headers."""
        return {
            "X-Auth-Request-Token": self.token,
            "X-Auth-Request-User": self.username,
        }


def create_gafaelfawr_user(
    data: NubladoData, name: str, mock_gafaelfawr: MockGafaelfawr
) -> GafaelfawrTestUser:
    """Create a Gafaelfawr user for testing.

    Parameters
    ----------
    name
        Name of the user, which must correspond to a file in
        :file:`tests/data/controller/users` ending with ``.json``.
    mock_gafaelfawr
        Gafaelfawr mock with which to register the user.

    Returns
    -------
    GafaelfawrTestUser
        Registered test user with associated token.
    """
    user = data.read_pydantic(GafaelfawrUserInfo, f"controller/users/{name}")
    mock_gafaelfawr.set_user_info(user.username, user)
    token = mock_gafaelfawr.create_token(user.username)
    return GafaelfawrTestUser(token=token, **user.model_dump())
