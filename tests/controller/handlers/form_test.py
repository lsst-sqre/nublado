"""Tests for the form handlers."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from rubin.gafaelfawr import MockGafaelfawr

from ..support.config import configure
from ..support.data import read_output_data
from ..support.gafaelfawr import GafaelfawrTestUser, get_no_spawn_user


@pytest.mark.asyncio
async def test_lab_form(client: AsyncClient, user: GafaelfawrTestUser) -> None:
    r = await client.get(
        f"/nublado/spawner/v1/lab-form/{user.username}",
        headers=user.to_test_headers(),
    )
    assert r.status_code == 200
    assert r.headers["Content-Type"] == "text/html; charset=utf-8"

    expected = read_output_data("standard", "lab-form.html").strip()
    assert r.text == expected


@pytest.mark.asyncio
async def test_default_size(
    client: AsyncClient, user: GafaelfawrTestUser
) -> None:
    await configure("sizes")
    r = await client.get(
        f"/nublado/spawner/v1/lab-form/{user.username}",
        headers=user.to_test_headers(),
    )
    assert r.status_code == 200
    expected = read_output_data("sizes", "lab-form.html").strip()
    assert r.text == expected


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
    client: AsyncClient, mock_gafaelfawr: MockGafaelfawr
) -> None:
    user = get_no_spawn_user(mock_gafaelfawr)
    r = await client.get(
        f"/nublado/spawner/v1/lab-form/{user.username}",
        headers=user.to_test_headers(),
    )
    assert r.status_code == 200
    expected = read_output_data("standard", "lab-unavailable.html").strip()
    assert r.text == expected
