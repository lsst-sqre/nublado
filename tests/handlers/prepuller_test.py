"""Tests for the prepuller handlers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_prepulls(client: AsyncClient, std_result_dir: Path) -> None:
    r = await client.get("/nublado/spawner/v1/prepulls")
    assert r.status_code == 200

    with (std_result_dir / "prepulls.json").open("r") as f:
        expected = json.load(f)
    assert r.json() == expected
