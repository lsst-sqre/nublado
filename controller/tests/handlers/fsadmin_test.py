"""Tests for fsadmin route."""

from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient
from safir.testing.kubernetes import MockKubernetesApi

from controller.models.domain.gafaelfawr import GafaelfawrUser
from controller.models.domain.kubernetes import PodPhase

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
    r = await client.post("/nublado/fsadmin/v1/service", json={})
    assert r.status_code == 204

    # Verify it's running
    r = await client.get("/nublado/fsadmin/v1/service")
    assert r.status_code == 204

    # Request it again; should detect it exists and
    # return immediately without actually doing anything.
    r = await client.get("/nublado/fsadmin/v1/service")
    assert r.status_code == 204

    # Wait for the reconcile time and then check again to make sure reconcile
    # didn't incorrectly remove it (a bug in versions <= 8.8.9).
    await asyncio.sleep(config.fsadmin.reconcile_interval.total_seconds())
    r = await client.get(
        "/nublado/fsadmin/v1/service", headers=user.to_headers()
    )
    assert r.status_code == 204

    # Remove it.
    r = await client.delete("/nublado/fsadmin/v1/service")
    assert r.status_code == 204

    # Make sure it's gone.
    r = await client.get("/nublado/fsadmin/v1/service")
    assert r.status_code == 404

    # Start it again.  This time with no POST body.
    r = await client.post(
        "/nublado/fsadmin/v1/service", headers=user.to_headers()
    )
    assert r.status_code == 204

    # Check that pod and namespace were created correctly
    namespace = "fsadmin"

    # We have the namespace...
    nses = await mock_kubernetes.list_namespace()
    assert len(nses.items) == 1
    assert nses.items[0].metadata.name == namespace

    # It has a pod...
    pods = await mock_kubernetes.list_namespaced_pod(namespace)
    assert len(pods.items) == 1

    pod = pods.items[0]
    # Verify that the pod's mountpoints look correct...
    mounts = pod.spec.containers[0].volume_mounts
    assert len(mounts) == 3
    prefixed = [x.mount_path.startswith("/user-filesystems/") for x in mounts]
    assert all(prefixed)

    # Check that reconciliation works...

    # We make the pod exit...
    await mock_kubernetes.patch_namespaced_pod_status(
        name=pod.metadata.name,
        namespace=namespace,
        body=[
            {
                "op": "replace",
                "path": "/status/phase",
                "value": PodPhase.SUCCEEDED.value,
            }
        ],
    )

    # We wait for reconciliation...
    await asyncio.sleep(config.fsadmin.reconcile_interval.total_seconds())

    # And check that the namespace is gone.
    nses = await mock_kubernetes.list_namespace()
    assert len(nses.items) == 0
