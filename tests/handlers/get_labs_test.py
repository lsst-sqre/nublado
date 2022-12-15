"""Test jupyterlabcontroller.handlers"""

from __future__ import annotations

import pytest
from httpx import AsyncClient, Response

from jupyterlabcontroller.models.context import Context


async def _auth_get(url: str, app_client: AsyncClient, token: str) -> Response:
    headers = {"Authorization": f"bearer {token}"}
    return await app_client.get(url, headers=headers)


@pytest.mark.asyncio
async def test_get_labs(
    app_client: AsyncClient, admin_context: Context
) -> None:
    response = await _auth_get(
        url="/nublado/spawner/v1/labs/",
        app_client=app_client,
        token="token-of-authority",
    )
    data = response.json()
    assert data == list()
