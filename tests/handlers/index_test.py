"""Test jupyterlabcontroller.handlers"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from jupyterlabcontroller.config import Configuration

"""Tests for the jupyterlabcontroller.handlers external routes."""


@pytest.mark.asyncio
async def test_get_external_index(
    config: Configuration,
    app_client: AsyncClient,
) -> None:
    """Test ``GET /nublado/``"""
    response = await app_client.get("/nublado/")
    assert response.status_code == 200
    data = response.json()
    metadata = data["metadata"]
    assert metadata["name"] == config.safir.name
    assert isinstance(metadata["version"], str)
    assert isinstance(metadata["description"], str)
    assert isinstance(metadata["repository_url"], str)


"""Tests for the jupyterlabcontroller.handlers internal routes."""


@pytest.mark.asyncio
async def test_get_internal_index(
    app_client: AsyncClient, config: Configuration
) -> None:
    """Test ``GET /``"""
    response = await app_client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == config.safir.name
    assert isinstance(data["version"], str)
    assert isinstance(data["description"], str)
    assert isinstance(data["repository_url"], str)
