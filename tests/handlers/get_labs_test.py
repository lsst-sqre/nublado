"""Test jupyterlabcontroller.handlers"""

from __future__ import annotations

import pytest
from httpx import AsyncClient, Response

from jupyterlabcontroller.config import Configuration


async def _auth_get(
    url: str, app_client: AsyncClient, config: Configuration, token: str
) -> Response:
    headers = {"Authorization": f"bearer {token}"}
    return await app_client.get(url, headers=headers)


@pytest.mark.asyncio
async def test_get_labs(
    app_client: AsyncClient,
    config: Configuration,
    admin_token: str,
) -> None:
    response = await _auth_get(
        url="/nublado/spawner/v1/labs",
        token=admin_token,
        app_client=app_client,
        config=config,
    )
    data = response.json()
    assert data == list()
