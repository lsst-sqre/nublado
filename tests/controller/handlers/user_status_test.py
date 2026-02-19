"""Test retrieving user status."""

import asyncio

import pytest
from httpx import AsyncClient
from safir.testing.kubernetes import MockKubernetesApi

from nublado.controller.config import Config
from nublado.controller.dependencies.context import context_dependency
from nublado.controller.factory import Factory
from nublado.controller.models.domain.kubernetes import PodPhase
from nublado.controller.models.v1.lab import LabSpecification

from ...support.constants import TEST_BASE_URL
from ...support.data import NubladoData
from ...support.gafaelfawr import GafaelfawrTestUser


@pytest.mark.asyncio
async def test_user_status(
    *,
    client: AsyncClient,
    config: Config,
    data: NubladoData,
    factory: Factory,
    user: GafaelfawrTestUser,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    assert user.quota
    assert user.quota.notebook
    lab = data.read_pydantic(
        LabSpecification, "controller/base/lab-specification"
    )

    # At the start, we shouldn't have any lab.
    r = await client.get(
        "/nublado/spawner/v1/user-status", headers=user.to_test_headers()
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
        headers=user.to_test_headers(),
    )
    assert r.status_code == 201
    assert r.headers["Location"] == (
        f"{TEST_BASE_URL}/nublado/spawner/v1/labs/{user.username}"
    )

    # Now the lab should exist and we should be able to get some user status.
    await asyncio.sleep(0.1)
    r = await client.get(
        "/nublado/spawner/v1/user-status", headers=user.to_test_headers()
    )
    assert r.status_code == 200
    data.assert_json_matches(r.json(), "controller/spawn/lab-status")

    # Change the pod status. This should not result in any change because
    # reconcile hasn't run yet.
    r = await client.get(
        "/nublado/spawner/v1/user-status", headers=user.to_test_headers()
    )
    assert r.status_code == 200
    data.assert_json_matches(r.json(), "controller/spawn/lab-status")

    # Force reconciliation. This should delete the lab and result in a 404
    # error.
    name = f"{user.username}-nb"
    namespace = f"userlabs-{user.username}"
    pod = await mock_kubernetes.read_namespaced_pod(name, namespace)
    pod.status.phase = PodPhase.FAILED.value
    assert context_dependency._process_context
    await context_dependency._process_context.lab_manager.reconcile()
    r = await client.get(
        "/nublado/spawner/v1/user-status", headers=user.to_test_headers()
    )
    assert r.status_code == 404
