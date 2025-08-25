"""Tests for fsadmin route."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from safir.testing.kubernetes import MockKubernetesApi

from controller.models.domain.gafaelfawr import GafaelfawrUser

from ..support.config import configure


@pytest.mark.asyncio
async def test_create_delete(
    client: AsyncClient,
    user: GafaelfawrUser,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    config = await configure("fsadmin", mock_kubernetes)

    # Check that there is no fsadmin instance
    r = await client.get("/nublado/fsadmin/v1/service")
    assert r.status_code == 404

    # Delete it.  Should be a successful no-op
    r = await client.delete("/nublado/fsadmin/v1/service")
    assert r.status_code == 204

    # Start fsadmin
    r = await client.post("/nublado/fsadmin/v1/service", json={"start": True})
    assert r.status_code == 204

    # Verify it's running
    r = await client.get("/nublado/fsadmin/v1/service")
    assert r.status_code == 204

    # Remove it.
    r = await client.delete("/nublado/fsadmin/v1/service")
    assert r.status_code == 204

    # Make sure it's gone.
    r = await client.get("/nublado/fsadmin/v1/service")
    assert r.status_code == 404

    # Try to start it with no POST body
    r = await client.post(
        "/nublado/fsadmin/v1/service", headers=user.to_headers()
    )
    assert r.status_code == 422

    # Try to start it with empty JSON body
    r = await client.post(
        "/nublado/fsadmin/v1/service", headers=user.to_headers(), json={}
    )
    assert r.status_code == 422

    # Try to start it with bad JSON body
    r = await client.post(
        "/nublado/fsadmin/v1/service",
        headers=user.to_headers(),
        json={"start": False},
    )
    assert r.status_code == 422

    # Try to start it with another bad JSON body
    r = await client.post(
        "/nublado/fsadmin/v1/service",
        headers=user.to_headers(),
        json={"stop": True},
    )
    assert r.status_code == 422

    # Start it for real
    r = await client.post(
        "/nublado/fsadmin/v1/service",
        headers=user.to_headers(),
        json={"start": True},
    )
    assert r.status_code == 204

    # Check that pod was created correctly
    namespace = "nublado"

    # Check that it has a pod.
    pod = next(
        p
        for p in (await mock_kubernetes.list_namespaced_pod(namespace)).items
        if p.metadata.name == config.fsadmin.pod_name
    )

    # Verify that the pod's mountpoints look correct.
    mounts = pod.spec.containers[0].volume_mounts
    assert len(mounts) == 3
    prefixed = [x.mount_path.startswith("/user-filesystems/") for x in mounts]
    assert all(prefixed)
