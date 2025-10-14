"""Test purge-planning functionality."""

import asyncio
from pathlib import Path

import pytest

from rubin.nublado.purger.config import Config
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
async def test_ctime(purger_config_low_ctime: Config) -> None:
    purger = Purger(config=purger_config_low_ctime)
    await asyncio.sleep(1)  # Let the file age
    await purger.plan()
    assert purger._plan is not None
    assert len(purger._plan.files) == 1
    assert purger._plan.files[0].path.name == "small"


@pytest.mark.asyncio
async def test_threshold(purger_config: Config, fake_root: Path) -> None:
    set_age(fake_root / "scratch" / "small", FileReason.ATIME, "3h")
    set_age(fake_root / "scratch" / "large", FileReason.ATIME, "3h")
    # Only "large" should be marked for removal
    purger = Purger(config=purger_config)
    await purger.plan()
    assert purger._plan is not None
    assert len(purger._plan.files) == 1
    assert purger._plan.files[0].path.name == "large"


@pytest.mark.asyncio
async def test_null(purger_config_no_small: Config, fake_root: Path) -> None:
    set_age(fake_root / "scratch" / "small", FileReason.ATIME, "1000w")
    set_age(fake_root / "scratch" / "small", FileReason.MTIME, "1000w")
    purger = Purger(config=purger_config_no_small)
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
