"""Fixtures for inithome testing."""

import os
from pathlib import Path

import pytest
from pyfakefs.fake_filesystem import FakeFilesystem, set_gid, set_uid


@pytest.fixture(autouse=True)
def migration_fs(fs: FakeFilesystem) -> FakeFilesystem:
    """Set up a fake file system for user migration tests."""
    set_uid(0)
    set_gid(0)
    fs.create_dir(Path("/home"), perm_bits=0o755)

    # Set up source directory
    fs.create_dir(Path("/home/coop"), perm_bits=0o755)
    os.chown(Path("/home/coop"), 20771023, 20771023)
    # Target directory
    fs.create_dir(Path("/home/ghoul"), perm_bits=0o0755)
    os.chown(Path("/home/ghoul"), 22810321, 22810321)
    set_uid(20771023)
    set_gid(20771023)
    fs.create_dir(Path("/home/coop/.ssh"), perm_bits=0o0700)
    fs.create_file(
        Path("/home/coop/.ssh/authorized_keys"),
        contents="this-is-an-rsa-key-no-really",
    )
    Path("/home/coop/.ssh/authorized_keys").chmod(0o0644)
    fs.create_file(Path("/home/coop/hello.txt"), contents="Hello, world!\n")
    Path("/home/coop/hello.txt").chmod(0o0600)
    fs.create_symlink(Path("/home/coop/hi"), Path("./hello.txt"))
    fs.create_symlink(Path("/home/coop/howdy"), Path("/home/coop/hello.txt"))

    return fs
