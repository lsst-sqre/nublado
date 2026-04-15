"""Tests for migrator route."""

import datetime

import pytest
from httpx import AsyncClient
from kubernetes_asyncio.client import (
    V1ContainerState,
    V1ContainerStateTerminated,
    V1ContainerStatus,
)
from safir.testing.kubernetes import MockKubernetesApi

from ...support.config import configure
from ...support.data import NubladoData
from ...support.gafaelfawr import GafaelfawrTestUser


@pytest.mark.asyncio
async def test_create_delete(
    client: AsyncClient,
    user: GafaelfawrTestUser,
    data: NubladoData,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    await configure(data, "migrator", mock_kubernetes)

    # No migrator pod should exist
    objects = mock_kubernetes.get_namespace_objects_for_test("nublado")
    pods = [
        o
        for o in objects
        if o.kind == "Pod" and o.metadata.name.startswith("migrator-")
    ]
    assert pods == []

    # Check that there is no migrator instance
    r = await client.get(
        "/nublado/migrator/v1/service",
        params={"old_user": "alice", "new_user": "bob"},
    )
    assert r.status_code == 204

    # Start an instance
    r = await client.post(
        "/nublado/migrator/v1/service",
        json={"old_user": "alice", "new_user": "bob"},
    )
    assert r.status_code == 200
    j = r.json()
    assert j["running"] is True
    assert j["exit_code"] is None

    # Check that it's still running when we get status.

    # Check that there is a migrator instance
    r = await client.get(
        "/nublado/migrator/v1/service",
        params={"old_user": "alice", "new_user": "bob"},
    )
    assert r.status_code == 200
    j = r.json()
    assert j["running"] is True
    assert j["exit_code"] is None

    # Get the migrator kubernetes Pod object
    objects = mock_kubernetes.get_namespace_objects_for_test("nublado")
    pod = next(
        o
        for o in objects
        if o.kind == "Pod" and o.metadata.name.startswith("migrator-")
    )
    assert pod is not None

    # Stop the pod
    pod.status.phase = "Succeeded"
    pod.status.container_statuses = [
        V1ContainerStatus(
            image=pod.spec.containers[0].image,
            image_id=pod.spec.containers[0].image,
            name="nublado-migrator",
            ready=False,
            restart_count=0,
            state=V1ContainerState(
                terminated=V1ContainerStateTerminated(
                    finished_at=datetime.datetime.now(tz=datetime.UTC),
                    exit_code=0,
                )
            ),
        )
    ]

    # Get the status
    r = await client.get(
        "/nublado/migrator/v1/service",
        params={"old_user": "alice", "new_user": "bob"},
    )
    assert r.status_code == 200
    j = r.json()
    # Check the fields
    assert j["running"] is False
    assert j["exit_code"] == 0
    assert j["start_time"] is not None
    assert j["end_time"] is not None
    elapsed = (
        datetime.datetime.fromisoformat(j["end_time"])
        - datetime.datetime.fromisoformat(j["start_time"])
    ).total_seconds()
    assert elapsed > 0

    # That should have caused a container deletion
    objects = mock_kubernetes.get_namespace_objects_for_test("nublado")
    pods = [
        o
        for o in objects
        if o.kind == "Pod" and o.metadata.name.startswith("migrator-")
    ]
    assert pods == []

    # But the status should remain, and the GET should be idempotent
    # Get the status
    r = await client.get(
        "/nublado/migrator/v1/service",
        params={"old_user": "alice", "new_user": "bob"},
    )
    assert r.status_code == 200
    j = r.json()
    assert j["running"] is False
    assert j["exit_code"] == 0
    assert j["start_time"] is not None
    assert j["end_time"] is not None
    re_elapsed = (
        datetime.datetime.fromisoformat(j["end_time"])
        - datetime.datetime.fromisoformat(j["start_time"])
    ).total_seconds()
    assert elapsed == re_elapsed


@pytest.mark.asyncio
async def test_conflict(
    client: AsyncClient,
    user: GafaelfawrTestUser,
    data: NubladoData,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    await configure(data, "migrator", mock_kubernetes)
    # No migrator should be running...
    objects = mock_kubernetes.get_namespace_objects_for_test("nublado")
    pods = [
        o
        for o in objects
        if o.kind == "Pod" and o.metadata.name.startswith("migrator-")
    ]
    assert pods == []

    # Check that there is no migrator instance
    r = await client.get(
        "/nublado/migrator/v1/service",
        params={"old_user": "alice", "new_user": "bob"},
    )
    assert r.status_code == 204

    # Start an instance
    r = await client.post(
        "/nublado/migrator/v1/service",
        json={"old_user": "alice", "new_user": "bob"},
    )
    assert r.status_code == 200
    j = r.json()
    assert j["running"] is True
    assert j["exit_code"] is None

    # Check that it's still running

    # Check that there is a migrator instance
    r = await client.get(
        "/nublado/migrator/v1/service",
        params={"old_user": "alice", "new_user": "bob"},
    )
    assert r.status_code == 200
    j = r.json()
    assert j["running"] is True
    assert j["exit_code"] is None

    # Get the kubernetes Pod object
    objects = mock_kubernetes.get_namespace_objects_for_test("nublado")
    pod = next(
        o
        for o in objects
        if o.kind == "Pod" and o.metadata.name.startswith("migrator-")
    )
    assert pod is not None

    # Ask for the same response in the other direction.
    # This should provoke a 409 Conflict.

    # Start an instance
    r = await client.post(
        "/nublado/migrator/v1/service",
        json={"old_user": "bob", "new_user": "alice"},
    )
    assert r.status_code == 409
