"""Test that CLI works."""

import subprocess
from pathlib import Path

import pytest

from rubin.nublado.purger.config import Config


def test_report(fake_root: Path, purger_config: Config) -> None:
    config_file = fake_root / "config.yaml"
    proc = subprocess.run(["rsp_report", "-c", str(config_file)], check=False)
    assert proc.returncode == 0


def test_purge(fake_root: Path, purger_config: Config) -> None:
    config_file = fake_root / "config.yaml"
    proc = subprocess.run(["rsp_purge", "-c", str(config_file)], check=False)
    assert proc.returncode == 0


def test_execute(fake_root: Path, purger_config: Config) -> None:
    config_file = fake_root / "config.yaml"
    proc = subprocess.run(["rsp_execute", "-c", str(config_file)], check=False)
    assert proc.returncode == 0


def test_bad_config_file() -> None:
    proc = subprocess.run(
        ["rsp_report", "-c", "/this/file/does/not/exist"], check=False
    )
    assert proc.returncode != 0


def test_bad_policy_file() -> None:
    proc = subprocess.run(["rsp_purge"], check=False)
    assert proc.returncode != 0


def test_env_config(
    fake_root: Path, purger_config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_file = fake_root / "config.yaml"
    monkeypatch.setenv("RSP_SCRATCHPURGER_CONFIG_FILE", str(config_file))
    proc = subprocess.run(["rsp_report"], check=False)
    assert proc.returncode == 0
