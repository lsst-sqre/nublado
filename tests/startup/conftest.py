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
def rsp_fs(
    data: Data, fs: FakeFilesystem, monkeypatch: pytest.MonkeyPatch
) -> FakeFilesystem:
    data_root = data.path("startup/files")
    fs.add_real_directory(data_root / "etc", target_path="/etc")
    fs.add_real_directory(
        data_root / "homedir", target_path="/home/hambone", read_only=False
    )
    fs.add_real_directory(
        data_root / "jupyterlab", target_path="/opt/lsst/software/jupyterlab"
    )
    fs.add_real_directory(Path(__file__).parent.parent / "data")
    fs.create_dir("/etc/nublado/startup")
    fs.create_dir("/scratch")

    monkeypatch.delenv("DAF_BUTLER_CACHE_DIRECTORY", raising=False)
    monkeypatch.delenv("TMPDIR", raising=False)

    monkeypatch.setenv("NUBLADO_HOME", "/home/hambone")
    monkeypatch.setenv("NUBLADO_RUNTIME_MOUNTS_DIR", "/etc/nublado")
    monkeypatch.setenv("SCRATCH_PATH", "/scratch")

    return fs
