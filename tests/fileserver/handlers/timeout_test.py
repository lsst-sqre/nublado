"""Tests for user cleanup."""

from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient
from safir.testing.kubernetes import MockKubernetesApi

from jupyterlabcontroller.models.domain.gafaelfawr import GafaelfawrUser

from ...support.config import configure
from ...support.docker import MockDockerRegistry
from ...support.fileserver import (
    create_ingress_for_user,
    create_working_ingress_for_user,
    delete_ingress_for_user,
)


@pytest.mark.asyncio
async def test_timeout_no_pod_start(
    client: AsyncClient,
    user: GafaelfawrUser,
    mock_docker: MockDockerRegistry,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    config = await configure("fileserver", mock_kubernetes)
    name = user.username
    namespace = config.fileserver.namespace

    # Tell the Kubernetes mock to leave newly-created pods in pending status
    # rather than having them start automatically, simulating a fileserver pod
    # that never starts.
    mock_kubernetes.initial_pod_phase = "Pending"

    # Confirm there are no fileservers running at the start of the test.
    r = await client.get("/nublado/fileserver/v1/users")
    assert r.json() == []

    # Create an Ingress to match the GafaelfawrIngress. In real Kubernetes,
    # the GafaelfawrIngress creation would trigger this.
    await create_working_ingress_for_user(mock_kubernetes, name, namespace)

    # Start a user fileserver.
    start_task = asyncio.create_task(
        client.get("/files", headers=user.to_headers())
    )

    # The start task will create the Job and then time out waiting for the Pod
    # to start, and then will attempt to clean up. We need to manually delete
    # the ingress for it, since otherwise it will block waiting for the
    # ingress to disappear.
    await asyncio.sleep(0.1)
    await delete_ingress_for_user(mock_kubernetes, name, namespace)

    # Check that the start call raised a timeout error as expected.
    with pytest.raises(TimeoutError):
        await start_task

    # Check that the fileserver user map is still clear.
    r = await client.get("/nublado/fileserver/v1/users")
    assert r.json() == []


@pytest.mark.asyncio
async def test_timeout_no_ingress(
    client: AsyncClient,
    user: GafaelfawrUser,
    mock_docker: MockDockerRegistry,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    config = await configure("fileserver", mock_kubernetes)
    save_fs_timeout = config.fileserver.creation_timeout
    # Set low for testing
    config.fileserver.creation_timeout = 1
    r = await client.get("/nublado/fileserver/v1/users")
    # No fileservers yet.
    assert r.json() == []
    # Start a user fileserver.  Expect a timeout, because no Ingress
    # was created (in real life, creating the GafaelfawrIngress
    # ought to have created the Ingress).
    with pytest.raises(TimeoutError):
        r = await client.get("/files", headers=user.to_headers())
    # Check that the fileserver user map is still clear
    r = await client.get("/nublado/fileserver/v1/users")
    assert r.json() == []
    # Set timeout back to initial value
    config.fileserver.creation_timeout = save_fs_timeout


@pytest.mark.asyncio
async def test_timeout_no_ingress_ip(
    client: AsyncClient,
    user: GafaelfawrUser,
    mock_docker: MockDockerRegistry,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    config = await configure("fileserver", mock_kubernetes)
    name = user.username
    namespace = config.fileserver.namespace
    save_fs_timeout = config.fileserver.creation_timeout
    # Set low for testing
    config.fileserver.creation_timeout = 1
    r = await client.get("/nublado/fileserver/v1/users")
    # No fileservers yet.
    assert r.json() == []

    async def start_fileserver() -> None:
        await client.get("/files", headers=user.to_headers())

    # Start a user fileserver.  Expect a timeout, because the Ingress
    # did not get an IP address within the timeout.  This is a much
    # more realistic error, because the GafaelfawrIngress creates the
    # Ingress almost immediately but it often takes some time for the
    # ingress-nginx controller to get it correctly configured
    # Start the fileserver
    task = asyncio.create_task(start_fileserver())
    # Check that task is running
    assert task.done() is False
    # Check there are no fileservers yet.
    r = await client.get("/nublado/fileserver/v1/users")
    assert r.json() == []
    await create_ingress_for_user(mock_kubernetes, name, namespace)
    # Check that the fileserver user map is still clear
    r = await client.get("/nublado/fileserver/v1/users")
    assert r.json() == []
    # Check that creation times out
    with pytest.raises(TimeoutError):
        await task

    # Set timeout back to initial value
    config.fileserver.creation_timeout = save_fs_timeout
