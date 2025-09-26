"""Fixtures for inithome testing."""

from __future__ import annotations

from pathlib import Path

import pytest
from pyfakefs.fake_filesystem import FakeFilesystem, set_gid, set_uid


@pytest.fixture
def privileged_fs(fs: FakeFilesystem) -> FakeFilesystem:
    """Set up a fake file system for tests.

    Sets the user to UID 0, GID 0, and creates the :file:`/home` path that the
    tests use as a parent directory.
    """
    set_uid(0)
    set_gid(0)
    fs.create_dir(Path("/home"), perm_bits=0o755)
    return fs
