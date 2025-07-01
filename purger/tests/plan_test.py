"""Test purge-planning functionality."""

import asyncio
from pathlib import Path

import pytest
import yaml
from rubin.nublado.purger.config import Config
from rubin.nublado.purger.exceptions import NotLockedError
from rubin.nublado.purger.models.plan import FileReason
from rubin.nublado.purger.purger import Purger

from .util import set_age


@pytest.mark.asyncio
async def test_all_new(purger_config: Config) -> None:
    purger = Purger(config=purger_config)
    assert purger._plan is None
    await purger.plan()
    assert purger._plan is not None
    # This is not, in fact, unreachable; put an error after it and you'll see.
    assert len(purger._plan.files) == 0  # type:ignore[unreachable]


@pytest.mark.asyncio
async def test_atime(purger_config: Config, fake_root: Path) -> None:
    set_age(fake_root / "scratch" / "large", FileReason.ATIME, "8h")
    purger = Purger(config=purger_config)
    await purger.plan()
    assert purger._plan is not None
    assert len(purger._plan.files) == 1
    assert purger._plan.files[0].path.name == "large"


@pytest.mark.asyncio
async def test_mtime(purger_config: Config, fake_root: Path) -> None:
    set_age(fake_root / "scratch" / "large", FileReason.MTIME, "8h")
    purger = Purger(config=purger_config)
    await purger.plan()
    assert purger._plan is not None
    assert len(purger._plan.files) == 1
    assert purger._plan.files[0].path.name == "large"


@pytest.mark.asyncio
async def test_ctime(purger_config: Config, fake_root: Path) -> None:
    # Rewrite policy doc with shorter ctime
    policy_doc = yaml.safe_load(purger_config.policy_file.read_text())
    policy_doc["directories"][0]["intervals"]["small"]["creation_interval"] = (
        "1s"
    )
    new_policy = yaml.dump(policy_doc)
    purger_config.policy_file.write_text(new_policy)
    purger = Purger(config=purger_config)
    await asyncio.sleep(1)  # Let the file age
    await purger.plan()
    assert purger._plan is not None
    assert len(purger._plan.files) == 1
    assert purger._plan.files[0].path.name == "small"


@pytest.mark.asyncio
async def test_threshold(fake_root: Path, purger_config: Config) -> None:
    set_age(fake_root / "scratch" / "small", FileReason.ATIME, "3h")
    set_age(fake_root / "scratch" / "large", FileReason.ATIME, "3h")
    # Only "large" should be marked for removal
    purger = Purger(config=purger_config)
    await purger.plan()
    assert purger._plan is not None
    assert len(purger._plan.files) == 1
    assert purger._plan.files[0].path.name == "large"


@pytest.mark.asyncio
async def test_null(fake_root: Path, purger_config: Config) -> None:
    # Rewrite policy doc with no "small"
    policy_doc = yaml.safe_load(purger_config.policy_file.read_text())
    del policy_doc["directories"][0]["intervals"]["small"]
    new_policy = yaml.dump(policy_doc)
    purger_config.policy_file.write_text(new_policy)

    set_age(fake_root / "scratch" / "small", FileReason.ATIME, "1000w")
    set_age(fake_root / "scratch" / "small", FileReason.MTIME, "1000w")
    purger = Purger(config=purger_config)
    await purger.plan()
    assert purger._plan is not None
    assert len(purger._plan.files) == 0


@pytest.mark.asyncio
async def test_subdir(purger_config: Config, fake_root: Path) -> None:
    set_age(
        fake_root / "scratch" / "foo" / "bar" / "large", FileReason.ATIME, "8h"
    )
    purger = Purger(config=purger_config)
    await purger.plan()
    assert purger._plan is not None
    assert len(purger._plan.files) == 1
    assert purger._plan.files[0].path.parent.name == "bar"
    assert purger._plan.files[0].path.name == "large"


@pytest.mark.asyncio
async def test_no_lock(purger_config: Config) -> None:
    purger = Purger(config=purger_config)
    with pytest.raises(NotLockedError):
        await purger._perform_plan()
