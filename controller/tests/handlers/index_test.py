"""Test the routes for the root path both internally and externally."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from controller.config import Config


@pytest.mark.asyncio
async def test_get_external_index(client: AsyncClient, config: Config) -> None:
    response = await client.get("/nublado")
    assert response.status_code == 200
    data = response.json()
    metadata = data["metadata"]
    assert metadata["name"] == config.safir.name
    assert isinstance(metadata["version"], str)
    assert isinstance(metadata["description"], str)
    assert isinstance(metadata["repository_url"], str)


@pytest.mark.asyncio
async def test_get_internal_index(client: AsyncClient, config: Config) -> None:
    response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == config.safir.name
    assert isinstance(data["version"], str)
    assert isinstance(data["description"], str)
    assert isinstance(data["repository_url"], str)
