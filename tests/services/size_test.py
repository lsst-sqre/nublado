from pathlib import Path

import pytest

from jupyterlabcontroller.config import Configuration
from jupyterlabcontroller.services.size import SizeManager

from ..support.check_file import check_file


@pytest.mark.asyncio
async def test_resources(config: Configuration, std_result_dir: Path) -> None:
    size_manager = SizeManager(sizes=config.lab.sizes)
    szr_str = f"{size_manager.resources}"
    check_file(szr_str, std_result_dir / "sizemanager-resources.txt")


@pytest.mark.asyncio
async def test_form(config: Configuration, std_result_dir: Path) -> None:
    size_manager = SizeManager(sizes=config.lab.sizes)
    szf_str = f"{size_manager.formdata}"
    check_file(szf_str, std_result_dir / "sizemanager-formdata.txt")
