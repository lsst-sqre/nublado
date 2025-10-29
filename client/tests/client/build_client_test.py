"""Test the client object."""

from structlog.stdlib import BoundLogger

from rubin.nublado.client import NubladoClient


def test_client(
    configured_logger: BoundLogger, username: str, token: str
) -> None:
    client = NubladoClient(
        username=username,
        token=token,
        logger=configured_logger,
    )
    assert client.username == "rachel"
