"""Tests for the form handlers."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from ...support.config import configure
from ...support.data import NubladoData
from ...support.gafaelfawr import GafaelfawrTestUser


@pytest.mark.asyncio
async def test_lab_form(
    client: AsyncClient, data: NubladoData, user: GafaelfawrTestUser
) -> None:
    r = await client.get(
        f"/nublado/spawner/v1/lab-form/{user.username}",
        headers=user.to_test_headers(),
    )
    assert r.status_code == 200
    assert r.headers["Content-Type"] == "text/html; charset=utf-8"

    data.assert_text_matches(r.text, "controller/html/lab-form.html")


@pytest.mark.asyncio
async def test_default_size(
    client: AsyncClient, data: NubladoData, user: GafaelfawrTestUser
) -> None:
    await configure(data, "sizes")
    r = await client.get(
        f"/nublado/spawner/v1/lab-form/{user.username}",
        headers=user.to_test_headers(),
    )
    assert r.status_code == 200
    data.assert_text_matches(r.text, "controller/html/lab-form-sizes.html")


@pytest.mark.asyncio
async def test_errors(client: AsyncClient, user: GafaelfawrTestUser) -> None:
    r = await client.get(
        "/nublado/spawner/v1/lab-form/otheruser",
        headers=user.to_test_headers(),
    )
    assert r.status_code == 403
    assert r.json() == {
        "detail": [{"msg": "Permission denied", "type": "permission_denied"}]
    }


@pytest.mark.asyncio
async def test_quota_spawn(
    client: AsyncClient, data: NubladoData, user_no_spawn: GafaelfawrTestUser
) -> None:
    r = await client.get(
        f"/nublado/spawner/v1/lab-form/{user_no_spawn.username}",
        headers=user_no_spawn.to_test_headers(),
    )
    assert r.status_code == 200
    data.assert_text_matches(r.text, "controller/html/lab-unavailable.html")
