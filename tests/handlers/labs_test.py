"""Tests for user lab routes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from jupyterlabcontroller.config import Configuration
from jupyterlabcontroller.constants import DROPDOWN_SENTINEL_VALUE
from jupyterlabcontroller.factory import Factory

from ..settings import TestObjectFactory
from ..support.constants import TEST_BASE_URL
from ..support.kubernetes import MockLabKubernetesApi


def strip_none(model: dict[str, Any]) -> dict[str, Any]:
    """Strip `None` values from a serialized Kubernetes object.

    Comparing Kubernetes objects against serialized expected output is a bit
    of a pain, since Kubernetes objects often contain tons of optional
    parameters and the ``to_dict`` serialization includes every parameter.
    The naive result is therefore tedious to read or understand.

    This function works around this by taking a serialized Kubernetes object
    and dropping all of the parameters that are set to `None`. The ``to_dict``
    form of a Kubernetes object should be passed through it first before
    comparing to the expected output.

    Parmaters
    ---------
    model
        Kubernetes model serialized with ``to_dict``.

    Returns
    -------
    dict
        Cleaned-up model with `None` parameters removed.
    """
    result = {}
    for key, value in model.items():
        if value is None:
            continue
        if isinstance(value, dict):
            value = strip_none(value)
        elif isinstance(value, list):
            list_result = []
            for item in value:
                if isinstance(item, dict):
                    item = strip_none(item)
                list_result.append(item)
            value = list_result
        result[key] = value
    return result


@pytest.mark.asyncio
async def test_lab_start_stop(
    client: AsyncClient, factory: Factory, obj_factory: TestObjectFactory
) -> None:
    token, user = obj_factory.get_user()
    lab = obj_factory.labspecs[0]
    size_manager = factory.create_size_manager()

    # No users should have running labs.
    r = await client.get("/nublado/spawner/v1/labs")
    assert r.status_code == 200
    assert r.json() == []
    r = await client.get(f"/nublado/spawner/v1/labs/{user.username}")
    assert r.status_code == 404
    r = await client.get(
        f"/nublado/spawner/v1/labs/{user.username}/events",
        headers={"X-Auth-Request-User": user.username},
    )
    assert r.status_code == 404

    # Create a lab.
    r = await client.post(
        f"/nublado/spawner/v1/labs/{user.username}/create",
        json={
            "options": {
                "image_list": [DROPDOWN_SENTINEL_VALUE],
                "image_dropdown": [lab.options.image_list],
                "size": [lab.options.size],
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

    # Get events for the lab. The mock Kubernetes layer immediately puts the
    # pod into running status by default, so the event stream should be
    # complete and shouldn't stall waiting for additional events. The content
    # of the events isn't tested here in detail; we'll do that separately.
    r = await client.get(
        f"/nublado/spawner/v1/labs/{user.username}/events",
        headers={"X-Auth-Request-User": user.username},
    )
    assert r.status_code == 200
    assert f"Operation complete for {user.username}" in r.text

    # The user's lab should now be visible.
    r = await client.get("/nublado/spawner/v1/labs")
    assert r.status_code == 200
    assert r.json() == [user.username]
    r = await client.get(f"/nublado/spawner/v1/labs/{user.username}")
    assert r.status_code == 200
    expected_resources = size_manager.resources(lab.options.size)
    expected_options = lab.options.dict()
    expected_options["image_dropdown"] = expected_options["image_list"]
    expected_options["image_list"] = None
    assert r.json() == {
        "env": lab.env,
        "events": [],
        "gid": user.gid,
        "groups": user.dict()["groups"],
        "internal_url": f"http://lab.userlabs-{user.username}:8888",
        "name": user.name,
        "options": expected_options,
        "quota": None,
        "pod": "missing",
        "resources": expected_resources.dict(),
        "status": "running",
        "uid": user.uid,
        "username": user.username,
    }

    # Stop the lab.
    r = await client.delete(f"/nublado/spawner/v1/labs/{user.username}")
    assert r.status_code == 204

    # Now it should be gone again.
    r = await client.get("/nublado/spawner/v1/labs")
    assert r.status_code == 200
    assert r.json() == []
    r = await client.get(f"/nublado/spawner/v1/labs/{user.username}")
    assert r.status_code == 404
    r = await client.get(
        f"/nublado/spawner/v1/labs/{user.username}/events",
        headers={"X-Auth-Request-User": user.username},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_lab_objects(
    client: AsyncClient,
    config: Configuration,
    mock_kubernetes: MockLabKubernetesApi,
    obj_factory: TestObjectFactory,
    std_result_dir: Path,
) -> None:
    token, user = obj_factory.get_user()
    lab = obj_factory.labspecs[0]

    r = await client.post(
        f"/nublado/spawner/v1/labs/{user.username}/create",
        json={"options": lab.options.dict(), "env": lab.env},
        headers={
            "X-Auth-Request-Token": token,
            "X-Auth-Request-User": user.username,
        },
    )
    assert r.status_code == 201

    namespace = f"{config.lab.namespace_prefix}-{user.username}"
    objects = mock_kubernetes.get_all_objects_in_namespace_for_test(namespace)
    with (std_result_dir / "lab-objects.json").open("r") as f:
        expected = json.load(f)
    assert [strip_none(o.to_dict()) for o in objects] == expected
