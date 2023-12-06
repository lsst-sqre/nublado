"""Test inithome functionality."""

import pyfakefs
import pytest
from rubin.nublado.inithome.provisioner import Provisioner

from .conftest import USERS


@pytest.mark.asyncio
async def test_provisioner_basic_(
    privileged_fs: pyfakefs.fake_filesystem.FakeFilesystem,
) -> None:
    user = USERS["gsamsa"]
    uid = user.uid
    gid = user.gid
    homedir = user.homedir

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
    privileged_fs: pyfakefs.fake_filesystem.FakeFilesystem,
) -> None:
    user = USERS["josephk"]
    uid = user.uid
    gid = user.gid
    homedir = user.homedir

    prov = Provisioner(uid=uid, gid=gid, homedir=homedir)
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
    # /home
    parent3_stat = homedir.parent.parent.parent.stat()
    assert parent3_stat.st_uid == 0
    assert parent3_stat.st_gid == 0
    assert (parent3_stat.st_mode & 0o777) == 0o755


@pytest.mark.asyncio
async def test_bad_ids() -> None:
    user = USERS["leni"]
    uid = user.uid
    gid = user.gid
    homedir = user.homedir
    # Negative IDs

    with pytest.raises(ValueError, match="UID/GID must be positive"):
        _ = Provisioner(uid=-1, gid=gid, homedir=homedir)
    with pytest.raises(ValueError, match="UID/GID must be positive"):
        _ = Provisioner(uid=uid, gid=-1, homedir=homedir)
    # Zero IDs
    with pytest.raises(ValueError, match="Will not provision for UID/GID 0"):
        _ = Provisioner(uid=0, gid=gid, homedir=homedir)
    with pytest.raises(ValueError, match="Will not provision for UID/GID 0"):
        _ = Provisioner(uid=uid, gid=0, homedir=homedir)
    with pytest.raises(ValueError, match="must be <="):
        _ = Provisioner(uid=int(6e9), gid=gid, homedir=homedir)
    with pytest.raises(ValueError, match="must be <="):
        _ = Provisioner(uid=uid, gid=int(6e9), homedir=homedir)


@pytest.mark.asyncio
async def test_existing_dir(
    privileged_fs: pyfakefs.fake_filesystem.FakeFilesystem,
) -> None:
    user = USERS["leni"]
    uid = user.uid
    gid = user.gid
    homedir = user.homedir

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
    privileged_fs: pyfakefs.fake_filesystem.FakeFilesystem,
) -> None:
    user = USERS["grubach"]
    uid = user.uid
    gid = user.gid
    homedir = user.homedir

    assert homedir.is_dir()
    stat_results = homedir.stat()
    assert stat_results.st_uid != uid
    assert stat_results.st_gid == gid
    assert (stat_results.st_mode & 0o777) == 0o700
    prov = Provisioner(uid=uid, gid=gid, homedir=homedir)
    with pytest.raises(RuntimeError, match="is owned by"):
        await prov.provision()

    user = USERS["karl"]
    uid = user.uid
    gid = user.gid
    homedir = user.homedir

    assert homedir.is_dir()
    stat_results = homedir.stat()
    assert stat_results.st_uid == uid
    assert stat_results.st_gid != gid
    assert (stat_results.st_mode & 0o777) == 0o700
    prov = Provisioner(uid=uid, gid=gid, homedir=homedir)
    with pytest.raises(RuntimeError, match="is owned by group"):
        await prov.provision()


@pytest.mark.asyncio
async def test_not_directory(
    privileged_fs: pyfakefs.fake_filesystem.FakeFilesystem,
    caplog: pytest.LogCaptureFixture,
) -> None:
    user = USERS["huld"]
    uid = user.uid
    gid = user.gid
    homedir = user.homedir
    assert not homedir.is_dir()
    stat_results = homedir.stat()
    assert stat_results.st_uid == uid
    assert stat_results.st_gid == gid
    assert (stat_results.st_mode & 0o777) == 0o700
    user = USERS["burstner"]
    uid = user.uid
    gid = user.gid
    homedir = user.homedir
    assert homedir.is_dir()
    stat_results = homedir.stat()
    assert stat_results.st_uid == uid
    assert stat_results.st_gid == gid
    assert (stat_results.st_mode & 0o777) == 0o775
    prov = Provisioner(uid=uid, gid=gid, homedir=homedir)
    await prov.provision()
    rec = caplog.records[0]
    assert "strange permissions" in rec.message
