"""Tests for the form handlers."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient

from ..settings import TestObjectFactory


@pytest.mark.asyncio
async def test_lab_form(
    client: AsyncClient, std_result_dir: Path, obj_factory: TestObjectFactory
) -> None:
    _, user = obj_factory.get_user()

    r = await client.get(
        f"/nublado/spawner/v1/lab-form/{user.username}",
        headers={"X-Auth-Request-User": user.username},
    )
    assert r.status_code == 200
    assert r.headers["Content-Type"] == "text/html; charset=utf-8"

    expected = (std_result_dir / "lab_form.txt").read_text().strip()
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
