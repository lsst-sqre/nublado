import json
from dataclasses import asdict
from pathlib import Path

import pytest

from jupyterlabcontroller.config import Configuration
from jupyterlabcontroller.services.size import SizeManager


@pytest.mark.asyncio
async def test_resources(config: Configuration, std_result_dir: Path) -> None:
    with (std_result_dir / "sizemanager-resources.json").open("r") as f:
        expected = json.load(f)
    size_manager = SizeManager(sizes=config.lab.sizes)
    resources = {k: v.dict() for k, v in size_manager.resources.items()}
    assert resources == expected


@pytest.mark.asyncio
async def test_form(config: Configuration, std_result_dir: Path) -> None:
    with (std_result_dir / "sizemanager-formdata.json").open("r") as f:
        expected = json.load(f)
    size_manager = SizeManager(sizes=config.lab.sizes)
    assert [asdict(d) for d in size_manager.formdata] == expected
