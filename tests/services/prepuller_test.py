from pathlib import Path

import pytest

from jupyterlabcontroller.factory import Factory


@pytest.mark.asyncio
async def test_get_menu_images(factory: Factory, std_result_dir: Path) -> None:
    prepuller_arbitrator = factory.create_prepuller_arbitrator()
    r = prepuller_arbitrator.get_menu_images()
    assert str(r) == (std_result_dir / "menu-images.txt").read_text()


@pytest.mark.asyncio
async def test_get_prepulls(factory: Factory, std_result_dir: Path) -> None:
    prepuller_arbitrator = factory.create_prepuller_arbitrator()
    r = prepuller_arbitrator.get_prepulls()
    assert str(r) == (std_result_dir / "prepulls.txt").read_text()
