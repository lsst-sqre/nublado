"""Tests for the jupyterlabcontroller.handlers.external module and routes."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from jupyterlabcontroller.models.v1.domain.config import Config


@pytest.mark.asyncio
async def test_get_index(client: AsyncClient, config: Config) -> None:
    """Test ``GET /jupyterlab-controller/``"""
    response = await client.get("/jupyterlab-controller/")
    assert response.status_code == 200
    data = response.json()
    metadata = data["metadata"]
    assert metadata["name"] == config.safir.name
    assert isinstance(metadata["version"], str)
    assert isinstance(metadata["description"], str)
    assert isinstance(metadata["repository_url"], str)
    assert isinstance(metadata["documentation_url"], str)
