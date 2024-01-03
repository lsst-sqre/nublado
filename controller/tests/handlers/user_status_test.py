"""Test retrieving user status."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from safir.testing.kubernetes import MockKubernetesApi

from controller.config import Config
from controller.factory import Factory
from controller.models.domain.gafaelfawr import GafaelfawrUser
from controller.models.domain.kubernetes import PodPhase

from ..support.constants import TEST_BASE_URL
from ..support.data import read_input_lab_specification_json, read_output_json


@pytest.mark.asyncio
async def test_user_status(
    client: AsyncClient,
    config: Config,
    factory: Factory,
    user: GafaelfawrUser,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    assert user.quota
    assert user.quota.notebook
    lab = read_input_lab_specification_json("base", "lab-specification")

    # At the start, we shouldn't have any lab.
    r = await client.get(
        "/nublado/spawner/v1/user-status", headers=user.to_headers()
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
        headers=user.to_headers(),
    )
    assert r.status_code == 201
    assert r.headers["Location"] == (
        f"{TEST_BASE_URL}/nublado/spawner/v1/labs/{user.username}"
    )

    # Now the lab should exist and we should be able to get some user status.
    r = await client.get(
        "/nublado/spawner/v1/user-status", headers=user.to_headers()
    )
    assert r.status_code == 200
    expected = read_output_json("standard", "lab-status")
    assert r.json() == expected

    # Change the pod phase. This should throw the lab into a terminated state.
    name = f"{user.username}-nb"
    namespace = f"userlabs-{user.username}"
    pod = await mock_kubernetes.read_namespaced_pod(name, namespace)
    pod.status.phase = PodPhase.FAILED.value
    r = await client.get(
        "/nublado/spawner/v1/user-status", headers=user.to_headers()
    )
    assert r.status_code == 200
    expected["status"] = "terminated"
    assert r.json() == expected

    # Delete the pod out from under the controller. This should also change
    # the pod status.
    await mock_kubernetes.delete_namespaced_pod(name, namespace)
    r = await client.get(
        "/nublado/spawner/v1/user-status", headers=user.to_headers()
    )
    assert r.status_code == 200
    expected["status"] = "failed"
    assert r.json() == expected
