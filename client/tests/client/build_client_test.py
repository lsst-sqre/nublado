"""Test the client object."""

from structlog.stdlib import BoundLogger

from rubin.nublado.client import NubladoClient
from rubin.nublado.client.models.user import AuthenticatedUser


def test_client(
    environment_url: str,
    configured_logger: BoundLogger,
    test_user: AuthenticatedUser,
) -> None:
    cl = NubladoClient(
        user=test_user, logger=configured_logger, base_url=environment_url
    )
    assert cl.user.username == "rachel"
