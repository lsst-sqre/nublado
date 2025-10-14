"""Test purging functionality."""

from pathlib import Path

import pytest

from rubin.nublado.purger.config import Config
from rubin.nublado.purger.models.plan import FileReason
from rubin.nublado.purger.purger import Purger

from .util import set_age


def assert_contents(root: Path, paths: set[Path]) -> None:
    """Assert that root contains only the paths in paths.

    Ignores root/config.yaml and root/policy.yaml
    """
    existing = set(root.glob("**/*"))
    paths = paths.union({root / "config.yaml", root / "policy.yaml"})
    assert paths == existing


@pytest.mark.asyncio
async def test_execute(purger_config: Config, fake_root: Path) -> None:
    set_age(fake_root / "scratch" / "large", FileReason.ATIME, "8h")
    purger = Purger(purger_config)
    spared = {
        fake_root / "scratch",
        fake_root / "scratch" / "small",
        fake_root / "scratch" / "medium",
        fake_root / "scratch" / "foo",
        fake_root / "scratch" / "foo" / "bar",
        fake_root / "scratch" / "foo" / "bar" / "small",
        fake_root / "scratch" / "foo" / "bar" / "medium",
        fake_root / "scratch" / "foo" / "bar" / "large",
    }
    await purger.execute()

    assert_contents(fake_root, spared)


@pytest.mark.asyncio
async def test_dry_run(purger_config: Config, fake_root: Path) -> None:
    set_age(fake_root / "scratch" / "large", FileReason.ATIME, "8h")
    purger_config.dry_run = True
    purger = Purger(config=purger_config)
    await purger.execute()

    spared = {
        fake_root / "scratch",
        fake_root / "scratch" / "small",
        fake_root / "scratch" / "medium",
        fake_root / "scratch" / "large",
        fake_root / "scratch" / "foo",
        fake_root / "scratch" / "foo" / "bar",
        fake_root / "scratch" / "foo" / "bar" / "small",
        fake_root / "scratch" / "foo" / "bar" / "medium",
        fake_root / "scratch" / "foo" / "bar" / "large",
    }

    assert_contents(fake_root, spared)


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
    await purger.execute()

    # The /scratch/foo/bar directory shouldn't have been
    # deleted because it is named in a policy as its own
    # directory to check, but the files in it should have
    # been deleted.
    spared = {
        fake_root / "scratch",
        fake_root / "scratch" / "small",
        fake_root / "scratch" / "medium",
        fake_root / "scratch" / "large",
        fake_root / "scratch" / "foo",
        fake_root / "scratch" / "foo" / "bar",
    }

    assert_contents(fake_root, spared)


@pytest.mark.asyncio
async def test_directory_removed(
    purger_config_small: Config, fake_root: Path
) -> None:
    victim_dir = fake_root / "scratch" / "foo" / "bar" / "delete_me"
    victim_dir.mkdir()
    victim_file = victim_dir / "sacrifice"
    victim_file.write_text("bye")
    set_age(victim_file, FileReason.ATIME, "1000w")

    purger = Purger(config=purger_config_small)
    await purger.execute()

    # Both victim_file and victim_dir should be gone, but
    # victim's parent ("bar") should still be there
    spared = {
        fake_root / "scratch",
        fake_root / "scratch" / "small",
        fake_root / "scratch" / "medium",
        fake_root / "scratch" / "large",
        fake_root / "scratch" / "foo",
        fake_root / "scratch" / "foo" / "bar",
        fake_root / "scratch" / "foo" / "bar" / "small",
        fake_root / "scratch" / "foo" / "bar" / "medium",
        fake_root / "scratch" / "foo" / "bar" / "large",
    }

    assert_contents(fake_root, spared)
