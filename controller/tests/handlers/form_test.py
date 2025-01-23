"""Tests for the form handlers."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from controller.models.domain.gafaelfawr import GafaelfawrUser

from ..support.data import read_output_data
from ..support.gafaelfawr import get_no_spawn_user


@pytest.mark.asyncio
async def test_lab_form(client: AsyncClient, user: GafaelfawrUser) -> None:
    r = await client.get(
        f"/nublado/spawner/v1/lab-form/{user.username}",
        headers=user.to_headers(),
    )
    assert r.status_code == 200
    assert r.headers["Content-Type"] == "text/html; charset=utf-8"

    expected = read_output_data("standard", "lab-form.html").strip()
    assert r.text == expected


@pytest.mark.asyncio
async def test_errors(client: AsyncClient, user: GafaelfawrUser) -> None:
    r = await client.get(
        "/nublado/spawner/v1/lab-form/otheruser",
        headers=user.to_headers(),
    )
    assert r.status_code == 403
    assert r.json() == {
        "detail": [{"msg": "Permission denied", "type": "permission_denied"}]
    }


@pytest.mark.asyncio
async def test_quota_spawn(client: AsyncClient) -> None:
    token, user = get_no_spawn_user()
    r = await client.get(
        f"/nublado/spawner/v1/lab-form/{user.username}",
        headers=user.to_headers(),
    )
    assert r.status_code == 200
    expected = read_output_data("standard", "lab-unavailable.html").strip()
    assert r.text == expected
