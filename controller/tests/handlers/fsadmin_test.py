"""Tests for fsadmin route."""

from __future__ import annotations

import asyncio
import datetime

import pytest
from httpx import AsyncClient
from safir.datetime import current_datetime
from safir.testing.kubernetes import MockKubernetesApi

from controller.models.domain.gafaelfawr import GafaelfawrUser

from ..support.config import configure


@pytest.mark.asyncio
async def test_create_delete(
    client: AsyncClient,
    user: GafaelfawrUser,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    # Check that there is no fsadmin instance
    r = await client.get("/nublado/fsadmin/v1/service")
    assert r.status_code == 404

    # Delete it.  Should be a successful no-op
    r = await client.delete("/nublado/fsadmin/v1/service")
    assert r.status_code == 204

    # Start fsadmin
    now = current_datetime(microseconds=True)
    r = await client.post("/nublado/fsadmin/v1/service", json={"start": True})
    assert r.status_code == 200
    # Verify that start time looks sane
    obj = r.json()
    started = datetime.datetime.fromisoformat(obj["start_time"])
    elapsed = started - now
    assert elapsed.total_seconds() >= 0

    # Verify it's running
    r = await client.get("/nublado/fsadmin/v1/service")
    assert r.status_code == 200

    # Try to start it again
    r = await client.post("/nublado/fsadmin/v1/service", json={"start": True})
    assert r.status_code == 200
    # Verify that start time did not change
    r = await client.get("/nublado/fsadmin/v1/service")
    assert r.status_code == 200
    obj = r.json()
    new_started = datetime.datetime.fromisoformat(obj["start_time"])
    assert started == new_started

    # Remove it.
    r = await client.delete("/nublado/fsadmin/v1/service")
    assert r.status_code == 204

    # Make sure it's gone.
    r = await client.get("/nublado/fsadmin/v1/service")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_bad_create(
    client: AsyncClient,
    user: GafaelfawrUser,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    # Try to start fsadmin pod with no POST body
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


@pytest.mark.asyncio
async def test_created_pod(
    client: AsyncClient,
    user: GafaelfawrUser,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    config = await configure("fsadmin", mock_kubernetes)
    # Start pod
    r = await client.post(
        "/nublado/fsadmin/v1/service",
        headers=user.to_headers(),
        json={"start": True},
    )
    assert r.status_code == 200

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
    assert len(mounts) == 5
    prefixed = [x.mount_path.startswith("/user-filesystems/") for x in mounts]
    assert all(prefixed)


@pytest.mark.asyncio
async def test_locking(
    client: AsyncClient,
    user: GafaelfawrUser,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    config = await configure("fsadmin", mock_kubernetes)
    namespace = "nublado"

    # Tell the Kubernetes mock to leave newly-created pods in pending status
    # rather than having them start automatically, simulating a pod
    # that never starts.
    mock_kubernetes.initial_pod_phase = "Pending"

    # Try to start pod (it won't, because it will go into Pending)
    post_task = asyncio.create_task(
        client.post(
            "/nublado/fsadmin/v1/service",
            headers=user.to_headers(),
            json={"start": True},
        )
    )
    assert post_task.done() is False
    await asyncio.sleep(0.01)  # The mock takes a little time to create the pod
    pod = next(
        p
        for p in (await mock_kubernetes.list_namespaced_pod(namespace)).items
        if p.metadata.name == config.fsadmin.pod_name
    )
    assert pod.status.phase == "Pending"
    # This one should block because it cannot get a lock.
    delete_task = asyncio.create_task(
        client.delete("/nublado/fsadmin/v1/service", headers=user.to_headers())
    )
    assert delete_task.done() is False

    # "start" the pod
    now = current_datetime(microseconds=True)
    await mock_kubernetes.patch_namespaced_pod_status(
        pod.metadata.name,
        namespace,
        body=[{"op": "replace", "path": "/status/phase", "value": "Running"}],
    )
    # The POST should run; that should create the pod and then release the
    # lock, at which point the DELETE should run and remove the pod.
    await asyncio.sleep(0.01)  # The mock takes a little while.
    assert post_task.done() is True
    assert delete_task.done() is True
    r = post_task.result()
    assert r.status_code == 200
    # Check that the POST result has a datetime which decodes to sometime
    # at or after when we patched the pod to start it.
    obj = r.json()
    started = datetime.datetime.fromisoformat(obj["start_time"])
    elapsed = started - now
    assert elapsed.total_seconds() >= 0
    # However, since that ran, then the DELETE should have run once it could
    # get the lock, and therefore we should currently not have a pod.
    r = delete_task.result()
    assert r.status_code == 204
    # Confirm that we do not have a pod.
    r = await client.get("/nublado/fsadmin/v1/service")
    assert r.status_code == 404
