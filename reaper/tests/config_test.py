"""Test configuration file."""

from pathlib import Path

from reaper.config import Config
from reaper.services.reaper import BuckDharma


def test_config_from_file(test_config: Path) -> None:
    """Test loading a config from a YAML file."""
    cfg = Config.from_file(test_config)
    boc = BuckDharma(cfg)
    boc.populate()
    boc.plan()
    boc.report()
