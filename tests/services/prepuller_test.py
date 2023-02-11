from pathlib import Path

import pytest

from jupyterlabcontroller.factory import Factory

from ..support.check_file import check_file


@pytest.mark.asyncio
async def test_get_menu_images(factory: Factory, std_result_dir: Path) -> None:
    prepuller_arbitrator = factory.create_prepuller_arbitrator()
    r = prepuller_arbitrator.get_menu_images()
    menu_str = f"{r}"
    check_file(menu_str, std_result_dir / "menu-images.txt")


@pytest.mark.asyncio
async def test_get_prepulls(factory: Factory, std_result_dir: Path) -> None:
    prepuller_arbitrator = factory.create_prepuller_arbitrator()
    r = prepuller_arbitrator.get_prepulls()
    prepull_str = f"{r}"
    check_file(prepull_str, std_result_dir / "prepulls.txt")
