"""Tests for purger configuration."""

import pytest

from nublado.purger.config import Config

from ..support.data import NubladoData


def test_env_override(
    data: NubladoData, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = Config.from_file(data.path("purger/config.yaml"))
    assert not config.debug
    assert not config.dry_run

    monkeypatch.setenv("NUBLADO_DRY_RUN", "true")
    monkeypatch.setenv("NUBLADO_DEBUG", "true")

    config = Config.from_file(data.path("purger/config.yaml"))
    assert config.debug
    assert config.dry_run
