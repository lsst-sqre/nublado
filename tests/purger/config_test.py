"""Tests for purger configuration."""

from pathlib import Path

import pytest

from nublado.purger.config import Config


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RSP_SCRATCHPURGER_DRY_RUN", "true")
    monkeypatch.setenv("RSP_SCRATCHPURGER_DEBUG", "true")

    config_file = (
        Path(__file__).parent.parent / "data" / "purger" / "config.yaml"
    )
    config = Config.from_file(config_file)

    assert config.debug
    assert config.dry_run
