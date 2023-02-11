import json
from dataclasses import asdict
from pathlib import Path

import pytest

from jupyterlabcontroller.factory import Factory


@pytest.mark.asyncio
async def test_get_menu_images(factory: Factory, std_result_dir: Path) -> None:
    with (std_result_dir / "menu-images.json").open("r") as f:
        expected = json.load(f)
    images = factory.image_service.menu_images()
    assert {
        "menu": [asdict(i) for i in images.menu],
        "dropdown": [asdict(i) for i in images.dropdown],
    } == expected


@pytest.mark.asyncio
async def test_get_prepulls(factory: Factory, std_result_dir: Path) -> None:
    with (std_result_dir / "prepulls.json").open("r") as f:
        expected = json.load(f)
    r = factory.image_service.prepull_status()
    assert r.dict() == expected
