"""Test the client object."""

from structlog.stdlib import BoundLogger

from rubin.nublado.client import GafaelfawrUser, NubladoClient


def test_client(
    environment_url: str,
    configured_logger: BoundLogger,
    test_user: GafaelfawrUser,
) -> None:
    cl = NubladoClient(
        user=test_user, logger=configured_logger, base_url=environment_url
    )
    assert cl.user.username == "rachel"
