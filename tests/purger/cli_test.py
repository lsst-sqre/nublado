"""Test that CLI works."""

import subprocess
from pathlib import Path

import pytest


@pytest.mark.usefixtures("purger_config")
def test_report(fake_root: Path) -> None:
    config_file = fake_root / "config.yaml"
    proc = subprocess.run(["rsp_report", "-c", str(config_file)], check=False)
    assert proc.returncode == 0


@pytest.mark.usefixtures("purger_config")
def test_purge(fake_root: Path) -> None:
    config_file = fake_root / "config.yaml"
    proc = subprocess.run(["rsp_purge", "-c", str(config_file)], check=False)
    assert proc.returncode == 0


@pytest.mark.usefixtures("purger_config")
def test_execute(fake_root: Path) -> None:
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


@pytest.mark.usefixtures("purger_config")
def test_env_config(fake_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_file = fake_root / "config.yaml"
    monkeypatch.setenv("RSP_SCRATCHPURGER_CONFIG_FILE", str(config_file))
    proc = subprocess.run(["rsp_report"], check=False)
    assert proc.returncode == 0


@pytest.mark.usefixtures("purger_config")
def test_cli_override(fake_root: Path) -> None:
    config_file = fake_root / "config.yaml"
    proc = subprocess.run(
        ["rsp_execute", "-c", str(config_file), "--dry-run"],
        check=False,
        capture_output=True,
    )
    assert proc.returncode == 0
    assert "Cannot purge because dry_run enabled" in str(proc.stdout)

    proc = subprocess.run(
        ["rsp_execute", "-c", str(config_file)],
        check=False,
        capture_output=True,
    )
    assert proc.returncode == 0
    assert "Cannot purge because dry_run enabled" not in str(proc.stdout)
