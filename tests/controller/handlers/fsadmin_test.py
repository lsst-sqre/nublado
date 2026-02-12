"""Tests for fsadmin route."""

from __future__ import annotations

import asyncio
import datetime

import pytest
from httpx import AsyncClient
from safir.datetime import current_datetime
from safir.testing.kubernetes import MockKubernetesApi

from ...support.config import configure
from ...support.data import assert_json_output_matches
from ...support.gafaelfawr import GafaelfawrTestUser
from ...support.kubernetes import objects_to_dicts


@pytest.mark.asyncio
async def test_create_delete(
    client: AsyncClient,
    user: GafaelfawrTestUser,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    # Check that there is no fsadmin instance
    r = await client.get("/nublado/fsadmin/v1/service")
    assert r.status_code == 404

    # Delete it.  Should be a successful no-op
    r = await client.delete("/nublado/fsadmin/v1/service")
    assert r.status_code == 204

    # Start fsadmin
    now = current_datetime()
    r = await client.post("/nublado/fsadmin/v1/service", json={"start": True})
    assert r.status_code == 200
    # Verify that start time looks sane
    obj = r.json()
    started = datetime.datetime.fromisoformat(obj["start_time"])
    elapsed = started - now
    assert elapsed.total_seconds() >= 0

    # # Verify it's running
    r = await client.get("/nublado/fsadmin/v1/service")
    assert r.status_code == 200

    # # Try to start it again
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
    user: GafaelfawrTestUser,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    # Try to start fsadmin pod with no POST body
    r = await client.post(
        "/nublado/fsadmin/v1/service", headers=user.to_test_headers()
    )
    assert r.status_code == 422

    # Try to start it with empty JSON body
    r = await client.post(
        "/nublado/fsadmin/v1/service", headers=user.to_test_headers(), json={}
    )
    assert r.status_code == 422

    # Try to start it with bad JSON body
    r = await client.post(
        "/nublado/fsadmin/v1/service",
        headers=user.to_test_headers(),
        json={"start": False},
    )
    assert r.status_code == 422

    # Try to start it with another bad JSON body
    r = await client.post(
        "/nublado/fsadmin/v1/service",
        headers=user.to_test_headers(),
        json={"stop": True},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_created_pod(
    client: AsyncClient,
    user: GafaelfawrTestUser,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    await configure("fsadmin", mock_kubernetes)
    # Start pod
    r = await client.post(
        "/nublado/fsadmin/v1/service",
        headers=user.to_test_headers(),
        json={"start": True},
    )
    assert r.status_code == 200

    # Verify that the pod is correct.
    objects = mock_kubernetes.get_namespace_objects_for_test("nublado")
    all_seen = objects_to_dicts(objects)
    fs_pod = next(
        x
        for x in all_seen
        if x["kind"] == "Pod" and x["metadata"]["name"] == "fsadmin"
    )
    fs_pvc = next(x for x in all_seen if x["kind"] == "PersistentVolumeClaim")
    fsadmin_objs = [fs_pvc, fs_pod]
    assert_json_output_matches(fsadmin_objs, "fsadmin", "fsadmin-objects")


@pytest.mark.asyncio
async def test_locking(
    client: AsyncClient,
    user: GafaelfawrTestUser,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    config = await configure("fsadmin", mock_kubernetes)
    namespace = "nublado"

    # Tell the Kubernetes mock to leave newly-created pods in pending status
    # rather than having them start automatically, simulating a pod
    # that never starts.
    mock_kubernetes.initial_pod_phase = "Pending"

    # The mock sets start time to pod creation time, and doesn't update it
    # when we patch it to "Running", so we need to capture the time *now*
    # rather than when the pod "starts" so the delta is positive.

    now = current_datetime()

    # Try to start pod (it won't, because it will go into Pending)
    post_task = asyncio.create_task(
        client.post(
            "/nublado/fsadmin/v1/service",
            headers=user.to_test_headers(),
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
        client.delete(
            "/nublado/fsadmin/v1/service", headers=user.to_test_headers()
        )
    )
    assert delete_task.done() is False

    # "start" the pod

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
