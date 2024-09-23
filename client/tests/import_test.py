"""Basic import functionality."""

import rubin.nublado.client


def test_import() -> None:
    """The test is really the above import."""
    nc = rubin.nublado.client.NubladoClient
    assert nc is not None
