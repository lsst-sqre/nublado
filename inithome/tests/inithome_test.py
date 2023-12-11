"""Test inithome functionality."""

import os
from pathlib import Path

import pytest
from pyfakefs.fake_filesystem import FakeFilesystem
from rubin.nublado.inithome.provisioner import Provisioner


@pytest.mark.asyncio
async def test_provisioner_basic_(
    privileged_fs: FakeFilesystem,
) -> None:
    uid = 2247
    gid = 200
    homedir = Path("/home/gregorsamsa")

    prov = Provisioner(uid=uid, gid=gid, homedir=homedir)
    await prov.provision()

    assert homedir.is_dir()
    stat_results = homedir.stat()
    assert stat_results.st_uid == uid
    assert stat_results.st_gid == gid
    assert (stat_results.st_mode & 0o777) == 0o700
    # Check that parent is root-owned and mode 0755
    parent_stat = homedir.parent.stat()
    assert parent_stat.st_uid == 0
    assert parent_stat.st_gid == 0
    assert (parent_stat.st_mode & 0o777) == 0o755


@pytest.mark.asyncio
async def test_provisioner_subdir(
    privileged_fs: FakeFilesystem,
) -> None:
    uid = 63928
    gid = 63928
    homedir = Path("/home/j/josephk/nublado")

    # Missing parent directory /home/j/josephk
    prov = Provisioner(uid=uid, gid=gid, homedir=homedir)
    with pytest.raises(FileNotFoundError):
        await prov.provision()

    # Create the parent directories and set their ownership/mode appropriately
    privileged_fs.create_dir(homedir.parent.parent, perm_bits=0o755)
    privileged_fs.create_dir(homedir.parent, perm_bits=0o700)
    os.chown(homedir.parent, uid=uid, gid=gid)

    # Try again
    await prov.provision()
    assert homedir.is_dir()
    stat_results = homedir.stat()
    assert stat_results.st_uid == uid
    assert stat_results.st_gid == gid
    assert (stat_results.st_mode & 0o777) == 0o700
    # /home/j/josephk
    parent1_stat = homedir.parent.stat()
    assert parent1_stat.st_uid == 63928
    assert parent1_stat.st_gid == 63928
    assert (parent1_stat.st_mode & 0o777) == 0o700
    # /home/j
    parent2_stat = homedir.parent.parent.stat()
    assert parent2_stat.st_uid == 0
    assert parent2_stat.st_gid == 0
    assert (parent2_stat.st_mode & 0o777) == 0o755


@pytest.mark.asyncio
async def test_bad_ids() -> None:
    uid = 2000
    gid = 200
    homedir = Path("/home/leni")
    # Negative IDs

    with pytest.raises(ValueError, match="UID/GID must be positive"):
        _ = Provisioner(uid=-1, gid=gid, homedir=homedir)
    with pytest.raises(ValueError, match="UID/GID must be positive"):
        _ = Provisioner(uid=uid, gid=-1, homedir=homedir)
    # Reserved IDs
    with pytest.raises(ValueError, match="Will not provision for reserved"):
        _ = Provisioner(uid=0, gid=gid, homedir=homedir)
    with pytest.raises(ValueError, match="Will not provision for reserved"):
        _ = Provisioner(uid=65534, gid=gid, homedir=homedir)
    with pytest.raises(ValueError, match="Will not provision for reserved"):
        _ = Provisioner(uid=65535, gid=gid, homedir=homedir)
    with pytest.raises(ValueError, match="Will not provision for reserved"):
        _ = Provisioner(uid=2**32 - 1, gid=gid, homedir=homedir)
    with pytest.raises(ValueError, match="Will not provision for reserved"):
        _ = Provisioner(uid=uid, gid=0, homedir=homedir)
    with pytest.raises(ValueError, match="Will not provision for reserved"):
        _ = Provisioner(uid=uid, gid=65534, homedir=homedir)
    with pytest.raises(ValueError, match="Will not provision for reserved"):
        _ = Provisioner(uid=uid, gid=65535, homedir=homedir)
    with pytest.raises(ValueError, match="Will not provision for reserved"):
        _ = Provisioner(uid=uid, gid=2**32 - 1, homedir=homedir)
    with pytest.raises(ValueError, match="must be <="):
        _ = Provisioner(uid=int(6e9), gid=gid, homedir=homedir)
    with pytest.raises(ValueError, match="must be <="):
        _ = Provisioner(uid=uid, gid=int(6e9), homedir=homedir)


@pytest.mark.asyncio
async def test_existing_dir(
    privileged_fs: FakeFilesystem,
) -> None:
    uid = 2000
    gid = 200
    homedir = Path("/home/leni")

    # Precreate directory for leni
    privileged_fs.create_dir(homedir, perm_bits=0o700)
    os.chown(homedir, uid=uid, gid=gid)

    assert homedir.is_dir()
    stat_results = homedir.stat()
    assert stat_results.st_uid == uid
    assert stat_results.st_gid == gid
    assert (stat_results.st_mode & 0o777) == 0o700
    prov = Provisioner(uid=uid, gid=gid, homedir=homedir)
    await prov.provision()
    stat_results = homedir.stat()
    assert stat_results.st_uid == uid
    assert stat_results.st_gid == gid
    assert (stat_results.st_mode & 0o777) == 0o700


@pytest.mark.asyncio
async def test_bad_ownership(
    privileged_fs: FakeFilesystem,
    caplog: pytest.LogCaptureFixture,
) -> None:
    uid = 9942
    gid = 500
    homedir = Path("/home/grubach")

    # Create directory with wrong owner for grubach
    privileged_fs.create_dir(homedir, perm_bits=0o700)
    os.chown(homedir, uid=9 + uid, gid=gid)
    # Put a file into it
    rentfile = Path(homedir / "rents")
    privileged_fs.create_file(Path(rentfile, contents="K: 200"))
    rentfile.chmod(0o600)
    os.chown(homedir, uid=9 + uid, gid=gid)

    assert homedir.is_dir()
    stat_results = homedir.stat()
    assert stat_results.st_uid != uid
    assert stat_results.st_gid == gid
    assert (stat_results.st_mode & 0o777) == 0o700
    prov = Provisioner(uid=uid, gid=gid, homedir=homedir)
    with pytest.raises(RuntimeError, match="and is not empty"):
        await prov.provision()

    uid = 1088
    gid = 500
    homedir = Path("/home/karl")

    # Create directory with wrong group for karl
    privileged_fs.create_dir(homedir, perm_bits=0o700)
    os.chown(homedir, uid=uid, gid=17 + gid)

    assert homedir.is_dir()
    stat_results = homedir.stat()
    assert stat_results.st_uid == uid
    assert stat_results.st_gid != gid
    assert (stat_results.st_mode & 0o777) == 0o700
    prov = Provisioner(uid=uid, gid=gid, homedir=homedir)
    await prov.provision()
    rec = caplog.records[0]
    assert "resetting ownership" in rec.message
    stat_results = homedir.stat()
    assert stat_results.st_uid == uid
    assert stat_results.st_gid == gid
    assert (stat_results.st_mode & 0o777) == 0o700


@pytest.mark.asyncio
async def test_not_directory(
    privileged_fs: FakeFilesystem,
    caplog: pytest.LogCaptureFixture,
) -> None:
    uid = 4346
    gid = 4346
    homedir = Path("/home/huld")
    # Create non-directory for huld
    privileged_fs.create_file(homedir, contents="huld")
    homedir.chmod(0o700)
    os.chown(homedir, uid=uid, gid=gid)
    assert not homedir.is_dir()
    stat_results = homedir.stat()
    assert stat_results.st_uid == uid
    assert stat_results.st_gid == gid
    assert (stat_results.st_mode & 0o777) == 0o700
    prov = Provisioner(uid=uid, gid=gid, homedir=homedir)
    with pytest.raises(RuntimeError, match="exists but is not a directory"):
        await prov.provision()


@pytest.mark.asyncio
async def test_wrong_permissions(
    privileged_fs: FakeFilesystem,
    caplog: pytest.LogCaptureFixture,
) -> None:
    uid = 7304
    gid = 7304
    homedir = Path("/home/burstner")

    # Create directory with wrong permissions for burstner
    privileged_fs.create_dir(homedir, perm_bits=0o775)
    os.chown(homedir, uid=uid, gid=gid)

    assert homedir.is_dir()
    stat_results = homedir.stat()
    assert stat_results.st_uid == uid
    assert stat_results.st_gid == gid
    assert (stat_results.st_mode & 0o777) == 0o775
    prov = Provisioner(uid=uid, gid=gid, homedir=homedir)
    await prov.provision()
    rec = caplog.records[0]
    assert "strange permissions" in rec.message
