"""Pytest configuration and fixtures."""

from pathlib import Path

import pytest
from pyfakefs.fake_filesystem import FakeFilesystem
from safir.testing.data import Data


@pytest.fixture
def data(request: pytest.FixtureRequest, fs: FakeFilesystem) -> Data:
    update = request.config.getoption("--update-test-data")
    return Data(
        Path(__file__).parent.parent / "data",
        fake_filesystem=fs,
        update_test_data=update,
    )


@pytest.fixture
def rsp_fs_no_config(
    data: Data, fs: FakeFilesystem, monkeypatch: pytest.MonkeyPatch
) -> FakeFilesystem:
    # Supply everything but lab-config.json
    data_root = data.path("startup/files")
    fs.add_real_file(
        data_root / "etc/dircolors.ansi-universal",
        target_path="/etc/dircolors.ansi-universal",
    )
    fs.add_real_directory(data_root / "etc/skel", target_path="/etc/skel")
    fs.add_real_directory(
        data_root / "etc/nublado/environment",
        target_path="/etc/nublado/environment",
    )
    fs.add_real_directory(
        data_root / "etc/nublado/secrets", target_path="/etc/nublado/secrets"
    )

    fs.add_real_directory(
        data_root / "homedir", target_path="/home/hambone", read_only=False
    )
    fs.add_real_directory(
        data_root / "jupyterlab", target_path="/opt/lsst/software/jupyterlab"
    )
    fs.add_real_directory(Path(__file__).parent.parent / "data")
    fs.create_dir("/etc/nublado/config")
    fs.create_dir("/etc/nublado/startup")
    fs.create_dir("/scratch")

    monkeypatch.delenv("DAF_BUTLER_CACHE_DIRECTORY", raising=False)
    monkeypatch.delenv("TMPDIR", raising=False)

    monkeypatch.setenv("NUBLADO_HOME", "/home/hambone")
    monkeypatch.setenv("NUBLADO_RUNTIME_MOUNTS_DIR", "/etc/nublado")
    monkeypatch.setenv("SCRATCH_PATH", "/scratch")

    return fs


@pytest.fixture
def rsp_fs(data: Data, rsp_fs_no_config: FakeFilesystem) -> FakeFilesystem:
    # Add a standard lab-config.json
    data_root = data.path("startup/files")
    rsp_fs_no_config.add_real_directory(
        data_root / "etc/nublado/config", target_path="/etc/nublado/config"
    )

    return rsp_fs_no_config
