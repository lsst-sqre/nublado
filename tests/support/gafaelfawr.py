"""Mock responses from Gafaelfawr."""

from __future__ import annotations

from rubin.gafaelfawr import MockGafaelfawr

from nublado.controller.models.domain.gafaelfawr import GafaelfawrUser

from .data import read_input_users_json

__all__ = [
    "GafaelfawrTestUser",
    "get_no_spawn_user",
]


class GafaelfawrTestUser(GafaelfawrUser):
    """Gafaelfawr user with token and methods useful for tests."""

    def to_test_headers(self) -> dict[str, str]:
        """Return the representation of this user as HTTP request headers."""
        return {
            "X-Auth-Request-Token": self.token,
            "X-Auth-Request-User": self.username,
        }


def get_no_spawn_user(mock_gafaelfawr: MockGafaelfawr) -> GafaelfawrTestUser:
    """Find a user whose quota says they can't spawn labs.

    Returns
    -------
    GafaelfawrUser
        User data for a user with a quota set that forbids spawning labs.
    """
    users = read_input_users_json("base", "users")
    for userinfo in users.values():
        if userinfo.quota and userinfo.quota.notebook:
            if not userinfo.quota.notebook.spawn:
                token = mock_gafaelfawr.create_token(userinfo.username)
                return GafaelfawrTestUser(token=token, **userinfo.model_dump())
    raise ValueError("No users found with a quota forbidding spawning")
