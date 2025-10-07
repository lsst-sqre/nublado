"""Test purging functionality."""

from pathlib import Path

import pytest

from rubin.nublado.purger.config import Config
from rubin.nublado.purger.models.plan import FileReason
from rubin.nublado.purger.purger import Purger

from .util import set_age


@pytest.mark.asyncio
async def test_purge(purger_config: Config, fake_root: Path) -> None:
    set_age(fake_root / "scratch" / "large", FileReason.ATIME, "8h")
    purger = Purger(purger_config)
    await purger.plan()
    assert purger._plan is not None
    assert len(purger._plan.files) == 1
    victim = purger._plan.files[0].path
    assert victim.name == "large"
    assert victim.is_file()
    await purger.purge()
    assert not victim.exists()


@pytest.mark.asyncio
async def test_dry_run(purger_config: Config, fake_root: Path) -> None:
    set_age(fake_root / "scratch" / "large", FileReason.ATIME, "8h")
    purger_config.dry_run = True
    purger = Purger(config=purger_config)
    await purger.plan()
    assert purger._plan is not None
    assert len(purger._plan.files) == 1
    victim = purger._plan.files[0].path
    assert victim.name == "large"
    assert victim.is_file()
    await purger.purge()
    # It should not have been deleted.
    assert victim.exists()


@pytest.mark.asyncio
async def test_named_directory_and_parent_not_removed(
    purger_config_small: Config, fake_root: Path
) -> None:
    for fn in ("small", "medium", "large"):
        set_age(
            fake_root / "scratch" / "foo" / "bar" / fn,
            FileReason.MTIME,
            "1000w",
        )
    purger = Purger(config=purger_config_small)
    await purger.plan()
    assert purger._plan is not None
    assert len(purger._plan.files) == 3
    victim = purger._plan.files[0].path.parent
    parent = purger._plan.files[0].path.parent.parent
    assert victim.name == "bar"
    assert victim.is_dir()
    assert parent.name == "foo"
    assert parent.is_dir()
    await purger.purge()
    # Victim should not have been deleted, because it is named in a policy as
    # its own directory to check.
    assert victim.exists()
    # Parent should not have been deleted, because it is the parent of a
    # directory named in a policy.
    assert parent.exists()


@pytest.mark.asyncio
async def test_directory_removed(
    purger_config_small: Config, fake_root: Path
) -> None:
    victim = fake_root / "scratch" / "foo" / "bar" / "delete_me"
    assert not victim.exists()
    victim.mkdir()
    assert victim.exists()
    vfile = victim / "sacrifice"
    vfile.write_text("bye")
    set_age(vfile, FileReason.ATIME, "1000w")
    purger = Purger(config=purger_config_small)
    await purger.plan()
    assert purger._plan is not None
    await purger.purge()
    # Both vfile and victim should be gone, but victim's parent ("bar")
    # should still be there
    assert not vfile.exists()
    assert not victim.exists()
    assert victim.parent.exists()
