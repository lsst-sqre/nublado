"""Test the client object."""

from structlog.stdlib import BoundLogger

from rubin.nublado.client import NubladoClient


def test_client(
    environment_url: str,
    configured_logger: BoundLogger,
    username: str,
    token: str,
) -> None:
    client = NubladoClient(
        username=username,
        token=token,
        logger=configured_logger,
        base_url=environment_url,
    )
    assert client.username == "rachel"
