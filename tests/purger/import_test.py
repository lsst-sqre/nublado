"""Test basic module functionality."""

import nublado.purger
from nublado.purger.config import Config


def test_import(purger_config: Config) -> None:
    p = nublado.purger.purger.Purger(config=purger_config)
    assert p is not None
