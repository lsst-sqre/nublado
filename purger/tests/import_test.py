"""Test basic module functionality."""

import rubin.nublado.purger
from rubin.nublado.purger.config import Config


def test_import(purger_config: Config) -> None:
    p = rubin.nublado.purger.purger.Purger(config=purger_config)
    assert p is not None
