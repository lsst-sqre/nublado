"""Test CST copier functionality."""

import json
import os
from pathlib import Path

import pytest
from rubin.nublado.cst_landing.exceptions import (
    DestinationError,
    DestinationIsDirectoryError,
    PrecheckError,
)
from rubin.nublado.cst_landing.provisioner import Provisioner


@pytest.mark.usefixtures("_fake_root")
def test_provisioner_basic() -> None:
    pr = Provisioner.from_env()

    fnames = [x.name for x in pr._source_files]
    outfiles = [pr._dest_dir / x for x in fnames]
    settings = (
        pr._home_dir
        / ".jupyter"
        / "lab"
        / "user-settings"
        / "@jupyterlab"
        / "docmanager-extension"
        / "plugin.jupyterlab-settings"
    )

    for outf in outfiles:
        assert not outf.exists()

    assert not settings.exists()

    pr.go()

    for outf in outfiles:
        assert outf.is_symlink()

    assert settings.is_file()
    s_obj = json.loads(settings.read_text())

    assert s_obj["defaultViewers"]["markdown"] == "Markdown Preview"


@pytest.mark.usefixtures("_fake_root")
def test_bad_source(monkeypatch: pytest.MonkeyPatch) -> None:
    srcdir = os.getenv("CST_LANDING_PAGE_SRC_DIR")
    assert srcdir is not None
    monkeypatch.setenv("CST_LANDING_PAGE_SRC_DIR", "/nonexistent")
    pr = Provisioner.from_env()
    with pytest.raises(PrecheckError):
        pr.go()
    monkeypatch.setenv("CST_LANDING_PAGE_SRC_DIR", srcdir)
    monkeypatch.setenv("CST_LANDING_PAGE_FILES", "nonexistent")
    pr = Provisioner.from_env()
    with pytest.raises(PrecheckError):
        pr.go()


def test_bad_homedir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NUBLADO_HOME", "/nonexistent")
    pr = Provisioner.from_env()
    with pytest.raises(PrecheckError):
        pr.go()


def test_bad_destination() -> None:
    pr = Provisioner.from_env()
    assert len(pr._source_files) != 0
    source_file = pr._source_files[0]
    destfile = pr._dest_dir / source_file.name

    if destfile.exists():
        # I mean technically you don't HAVE to run all the tests in order.
        # So you might not already have the file here.
        assert destfile.is_symlink()
        assert destfile.readlink() == source_file
        destfile.unlink()

    # Directory
    destfile.mkdir(parents=True, exist_ok=True)
    with pytest.raises(DestinationIsDirectoryError):
        pr.go()
    destfile.rmdir()

    # FIFO
    os.mkfifo(str(destfile), 0o600)
    with pytest.raises(DestinationError):
        pr.go()
    destfile.unlink()

    # File
    destfile.write_text("!dlroW olleH\n")
    assert destfile.is_file()
    pr.go()
    assert destfile.is_symlink()
    assert destfile.readlink() == source_file
    destfile.unlink()

    # Link, but wrong
    destfile.symlink_to(Path("broken_link"))
    assert destfile.is_symlink()
    assert destfile.readlink() != source_file
    pr.go()
    assert destfile.is_symlink()
    assert destfile.readlink() == source_file
