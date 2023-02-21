import json
from pathlib import Path

import pytest

from jupyterlabcontroller.factory import Factory


@pytest.mark.asyncio
async def test_get_menu_images(factory: Factory, std_result_dir: Path) -> None:
    with (std_result_dir / "menu-images.json").open("r") as f:
        expected = json.load(f)
    prepuller_arbitrator = factory.create_prepuller_arbitrator()
    r = prepuller_arbitrator.get_menu_images()
    assert {
        "menu": {k: v.dict() for k, v in r.menu.items()},
        "all": {k: v.dict() for k, v in r.all.items()},
    } == expected


@pytest.mark.asyncio
async def test_get_prepulls(factory: Factory, std_result_dir: Path) -> None:
    with (std_result_dir / "prepulls.json").open("r") as f:
        expected = json.load(f)
    prepuller_arbitrator = factory.create_prepuller_arbitrator()
    r = prepuller_arbitrator.get_prepulls()
    assert r.dict() == expected
