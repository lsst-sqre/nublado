"""Fixtures for inithome testing."""

from pathlib import Path

import pytest
from pyfakefs.fake_filesystem import FakeFilesystem, set_gid, set_uid


@pytest.fixture
def privileged_fs(fs: FakeFilesystem) -> FakeFilesystem:
    # We do our work pretending to be root
    set_uid(0)
    set_gid(0)
    # Create a top-level /home directory
    fs.create_dir(Path("/home"), perm_bits=0o755)

    return fs
