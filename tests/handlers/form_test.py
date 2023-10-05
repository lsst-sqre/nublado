"""Tests for the form handlers."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from jupyterlabcontroller.models.domain.gafaelfawr import GafaelfawrUser

from ..support.data import read_output_data


@pytest.mark.asyncio
async def test_lab_form(client: AsyncClient, user: GafaelfawrUser) -> None:
    r = await client.get(
        f"/nublado/spawner/v1/lab-form/{user.username}",
        headers=user.to_headers(),
    )
    assert r.status_code == 200
    assert r.headers["Content-Type"] == "text/html; charset=utf-8"

    expected = read_output_data("standard", "lab_form.txt").strip()
    assert r.text == expected


@pytest.mark.asyncio
async def test_errors(client: AsyncClient) -> None:
    r = await client.get(
        "/nublado/spawner/v1/lab-form/someuser",
        headers={"X-Auth-Request-User": "otheruser"},
    )
    assert r.status_code == 403
    assert r.json() == {
        "detail": [{"msg": "Permission denied", "type": "permission_denied"}]
    }
