"""Tests for the size manager."""

from __future__ import annotations

from dataclasses import asdict

import pytest

from controller.config import Config
from controller.models.v1.lab import LabSize
from controller.services.size import SizeManager

from ..support.data import read_output_json


@pytest.mark.asyncio
async def test_resources(config: Config) -> None:
    expected = read_output_json("standard", "sizemanager-resources.json")
    size_manager = SizeManager(sizes=config.lab.sizes)
    for size, resources in expected.items():
        assert size_manager.resources(LabSize(size)).model_dump() == resources


@pytest.mark.asyncio
async def test_form(config: Config) -> None:
    expected = read_output_json("standard", "sizemanager-formdata.json")
    size_manager = SizeManager(sizes=config.lab.sizes)
    assert [asdict(d) for d in size_manager.formdata()] == expected
