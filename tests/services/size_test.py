from pathlib import Path

import pytest

from jupyterlabcontroller.config import Configuration
from jupyterlabcontroller.services.size import SizeManager


@pytest.mark.asyncio
async def test_resources(config: Configuration, std_result_dir: Path) -> None:
    size_manager = SizeManager(sizes=config.lab.sizes)
    resources = str(size_manager.resources)
    expected = (std_result_dir / "sizemanager-resources.txt").read_text()
    assert resources == expected


@pytest.mark.asyncio
async def test_form(config: Configuration, std_result_dir: Path) -> None:
    size_manager = SizeManager(sizes=config.lab.sizes)
    formdata = str(size_manager.formdata)
    expected = (std_result_dir / "sizemanager-formdata.txt").read_text()
    assert formdata == expected
