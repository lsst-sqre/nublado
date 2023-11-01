"""Tests for the prepuller handlers."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from ..support.data import read_output_json


@pytest.mark.asyncio
async def test_images(client: AsyncClient) -> None:
    r = await client.get("/nublado/spawner/v1/images")
    assert r.status_code == 200
    assert r.json() == read_output_json("standard", "images.json")


@pytest.mark.asyncio
async def test_prepulls(client: AsyncClient) -> None:
    r = await client.get("/nublado/spawner/v1/prepulls")
    assert r.status_code == 200
    assert r.json() == read_output_json("standard", "prepulls.json")
