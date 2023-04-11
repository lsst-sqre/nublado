"""Test retrieving user status."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from jupyterlabcontroller.factory import Factory

from ..settings import TestObjectFactory
from ..support.constants import TEST_BASE_URL


@pytest.mark.asyncio
async def test_user_status(
    client: AsyncClient, factory: Factory, obj_factory: TestObjectFactory
) -> None:
    token, user = obj_factory.get_user()
    lab = obj_factory.labspecs[0]
    size_manager = factory.create_size_manager()

    # At the start, we shouldn't have any lab.
    r = await client.get(
        "/nublado/spawner/v1/user-status",
        headers={"X-Auth-Request-User": user.username},
    )
    assert r.status_code == 404
    assert r.json() == {
        "detail": [
            {"msg": f"Unknown user {user.username}", "type": "unknown_user"}
        ]
    }

    # Create a lab.
    r = await client.post(
        f"/nublado/spawner/v1/labs/{user.username}/create",
        json={
            "options": {
                "image_list": [lab.options.image_list],
                "size": [lab.options.size.value],
            },
            "env": lab.env,
        },
        headers={
            "X-Auth-Request-Token": token,
            "X-Auth-Request-User": user.username,
        },
    )
    assert r.status_code == 201
    assert r.headers["Location"] == (
        f"{TEST_BASE_URL}/nublado/spawner/v1/labs/{user.username}"
    )

    # Now the lab should exist and we should be able to get some user status.
    r = await client.get(
        "/nublado/spawner/v1/user-status",
        headers={"X-Auth-Request-User": user.username},
    )
    assert r.status_code == 200
    expected_resources = size_manager.resources(lab.options.size)
    assert r.json() == {
        "env": lab.env,
        "events": [],
        "gid": user.gid,
        "groups": user.dict()["groups"],
        "internal_url": "http://lab.userlabs-rachel:8888",
        "name": user.name,
        "options": lab.options.dict(),
        "quota": None,
        "pod": "present",
        "resources": expected_resources.dict(),
        "status": "running",
        "uid": user.uid,
        "username": user.username,
    }
