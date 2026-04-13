"""Tests for migration."""

import stat
from pathlib import Path

import pytest
from pyfakefs.fake_filesystem import set_gid, set_uid

from nublado.migrator import Migrator


def test_migration() -> None:
    """Test happy path."""
    mg = Migrator(
        old_user="coop",
        new_user="ghoul",
        old_homedir="/home/coop",
        new_homedir="/home/ghoul",
    )
    dest = sorted(Path("/home/ghoul").glob("migrated-coop-*"))
    assert not dest  # Should be empty.
    # Run as "root"
    set_uid(0)
    set_gid(0)
    mg.go()
    dest = sorted(Path("/home/ghoul").glob("migrated-coop-*"))
    assert dest  # Should not be empty anymore.
    tgt = dest[0]
    hello = tgt / "hello.txt"
    hstat = hello.stat()
    # Does copy have new UID/GID?
    assert hstat.st_uid == 22810321
    assert hstat.st_gid == 22810321
    # Mode 0o0600?
    assert stat.S_IMODE(hstat.st_mode) == 0o0600
    # Right contents?
    assert hello.read_text() == "Hello, world!\n"
    # Test symlinks
    assert (tgt / "hi").is_symlink()
    assert (tgt / "howdy").is_symlink()
    # Relative symlinks stay relative
    assert (tgt / "hi").readlink() == Path("./hello.txt")
    # Absolute symlinks are unchanged
    assert (tgt / "howdy").readlink() == Path("/home/coop/hello.txt")
    # directory
    assert (tgt / ".ssh").is_dir()
    assert stat.S_IMODE((tgt / ".ssh").stat().st_mode) == 0o0700
    ak = tgt / ".ssh" / "authorized_keys"
    assert ak.is_file()
    assert stat.S_IMODE(ak.stat().st_mode) == 0o0644
    assert ak.read_text() == "this-is-an-rsa-key-no-really"


def test_bad_source() -> None:
    """No source directory."""
    with pytest.raises(SystemExit) as exc:
        _ = Migrator(
            old_user="coop",
            new_user="ghoul",
            old_homedir="/home/nonexistent",
            new_homedir="/home/ghoul",
        )
    assert exc.value.code == 4


def test_bad_target() -> None:
    """No target directory."""
    with pytest.raises(SystemExit) as exc:
        _ = Migrator(
            old_user="coop",
            new_user="ghoul",
            old_homedir="/home/coop",
            new_homedir="/home/nonexistent",
        )
    assert exc.value.code == 5


def test_bad_copy() -> None:
    """Copy failed."""
    with pytest.raises(SystemExit) as exc:
        mg = Migrator(
            old_user="coop",
            new_user="ghoul",
            old_homedir="/home/coop",
            new_homedir="/home/ghoul",
        )
        # Non-root user
        set_uid(65534)
        set_gid(65534)
        mg.go()
    assert exc.value.code == 6


def test_bad_chown() -> None:
    """Chown failed."""
    with pytest.raises(SystemExit) as exc:
        mg = Migrator(
            old_user="coop",
            new_user="ghoul",
            old_homedir="/home/coop",
            new_homedir="/home/ghoul",
        )
        # Copy as root
        set_uid(0)
        set_gid(0)
        mg._copy_files()
        # Try chown as non-root
        set_uid(65534)
        set_gid(65534)
        mg._chown_files()
    assert exc.value.code == 7
