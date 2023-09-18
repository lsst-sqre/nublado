import json
from dataclasses import asdict
from pathlib import Path

import pytest

from jupyterlabcontroller.config import Config
from jupyterlabcontroller.models.v1.lab import LabSize
from jupyterlabcontroller.services.size import SizeManager


@pytest.mark.asyncio
async def test_resources(config: Config, std_result_dir: Path) -> None:
    with (std_result_dir / "sizemanager-resources.json").open("r") as f:
        expected = json.load(f)
    size_manager = SizeManager(sizes=config.lab.sizes)
    for size, resources in expected.items():
        assert size_manager.resources(LabSize(size)).model_dump() == resources


@pytest.mark.asyncio
async def test_form(config: Config, std_result_dir: Path) -> None:
    with (std_result_dir / "sizemanager-formdata.json").open("r") as f:
        expected = json.load(f)
    size_manager = SizeManager(sizes=config.lab.sizes)
    assert [asdict(d) for d in size_manager.formdata()] == expected
