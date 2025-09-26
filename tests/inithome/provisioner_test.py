"""Test inithome functionality."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pyfakefs.fake_filesystem import FakeFilesystem

from rubin.nublado.inithome.provisioner import InvalidHomeError, Provisioner


@pytest.mark.asyncio
async def test_provisioner_basic(privileged_fs: FakeFilesystem) -> None:
    uid = 2247
    gid = 200
    home = Path("/home/gregorsamsa")

    provisioner = Provisioner(home, uid, gid)
    await provisioner.provision()

    assert home.is_dir()
    stat = home.stat()
    assert stat.st_uid == uid
    assert stat.st_gid == gid
    assert (stat.st_mode & 0o777) == 0o700


@pytest.mark.asyncio
async def test_provisioner_subdir(privileged_fs: FakeFilesystem) -> None:
    uid = 63928
    gid = 63928
    home = Path("/home/j/josephk/nublado")

    # Missing parent directory /home/j/josephk
    provisioner = Provisioner(home, uid, gid)
    with pytest.raises(FileNotFoundError):
        await provisioner.provision()

    # Create the parent directories and set their ownership/mode appropriately.
    privileged_fs.create_dir(home.parent.parent, perm_bits=0o755)
    privileged_fs.create_dir(home.parent, perm_bits=0o700)
    os.chown(home.parent, uid, gid)

    # Try again.
    await provisioner.provision()
    assert home.is_dir()
    stat = home.stat()
    assert stat.st_uid == uid
    assert stat.st_gid == gid
    assert (stat.st_mode & 0o777) == 0o700


@pytest.mark.asyncio
async def test_bad_ids() -> None:
    uid = 2000
    gid = 200
    home = Path("/home/leni")

    with pytest.raises(ValueError, match="must be nonnegative"):
        Provisioner(home, -1, gid)
    with pytest.raises(ValueError, match="must be nonnegative"):
        Provisioner(home, uid, -1)
    with pytest.raises(ValueError, match="out of range"):
        Provisioner(home, 2**32 - 1, gid)
    with pytest.raises(ValueError, match="out of range"):
        Provisioner(home, uid, 2**32 - 1)


@pytest.mark.asyncio
async def test_existing_dir(
    privileged_fs: FakeFilesystem,
    caplog: pytest.LogCaptureFixture,
) -> None:
    uid = 2000
    gid = 200
    home = Path("/home/leni")

    # Precreate directory for leni
    privileged_fs.create_dir(home, perm_bits=0o700)
    os.chown(home, uid, gid)

    # Running provisioning should do nothing, silently.
    provisioner = Provisioner(home, uid, gid)
    await provisioner.provision()
    stat = home.stat()
    assert stat.st_uid == uid
    assert stat.st_gid == gid
    assert (stat.st_mode & 0o777) == 0o700
    assert len(caplog.records) == 0


@pytest.mark.asyncio
async def test_bad_ownership(
    privileged_fs: FakeFilesystem,
    caplog: pytest.LogCaptureFixture,
) -> None:
    uid = 9942
    gid = 500
    home = Path("/home/grubach")

    # Create directory with wrong owner for grubach
    privileged_fs.create_dir(home, perm_bits=0o700)
    os.chown(home, uid=9 + uid, gid=gid)

    # Put a file into it.
    rentfile = Path(home / "rents")
    privileged_fs.create_file(rentfile, contents="K: 200")
    rentfile.chmod(0o600)
    os.chown(rentfile, uid=9 + uid, gid=gid)

    # Provisioning should fail.
    provisioner = Provisioner(home, uid, gid)
    with pytest.raises(InvalidHomeError, match="and is not empty"):
        await provisioner.provision()

    uid = 1088
    gid = 500
    home = Path("/home/karl")

    # Create directory with wrong group for karl, but this time leave it empty.
    privileged_fs.create_dir(home, perm_bits=0o700)
    os.chown(home, uid=uid, gid=17 + gid)

    # Provisioning should succeed with a message and fix the ownership.
    provisioner = Provisioner(home, uid, gid)
    await provisioner.provision()
    assert len(caplog.records) == 1
    assert "resetting ownership" in caplog.records[0].message
    stat = home.stat()
    assert stat.st_uid == uid
    assert stat.st_gid == gid
    assert (stat.st_mode & 0o777) == 0o700


@pytest.mark.asyncio
async def test_not_directory(
    privileged_fs: FakeFilesystem,
    caplog: pytest.LogCaptureFixture,
) -> None:
    uid = 4346
    gid = 4346
    home = Path("/home/huld")

    # Create non-directory for huld.
    privileged_fs.create_file(home, contents="huld")
    home.chmod(0o700)
    os.chown(home, uid=uid, gid=gid)

    # Provisioning should fail.
    provisioner = Provisioner(home, uid, gid)
    with pytest.raises(InvalidHomeError, match="but is not a directory"):
        await provisioner.provision()


@pytest.mark.asyncio
async def test_wrong_permissions(
    privileged_fs: FakeFilesystem,
    caplog: pytest.LogCaptureFixture,
) -> None:
    uid = 7304
    gid = 7304
    home = Path("/home/burstner")

    # Create directory with wrong permissions for burstner.
    privileged_fs.create_dir(home, perm_bits=0o775)
    os.chown(home, uid=uid, gid=gid)

    # Provisioning should succeed but log a warning.
    provisioner = Provisioner(home, uid, gid)
    await provisioner.provision()
    assert len(caplog.records) == 1
    assert "unexpected permissions" in caplog.records[0].message
