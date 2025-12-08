"""Test basic module functionality."""

from nublado.purger.config import Config
from nublado.purger.purger import Purger


def test_import(purger_config: Config) -> None:
    p = Purger(config=purger_config)
    assert p is not None
