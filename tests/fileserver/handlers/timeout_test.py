"""Tests for user cleanup."""

from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient
from safir.testing.kubernetes import MockKubernetesApi

from jupyterlabcontroller.config import Config

from ...settings import TestObjectFactory
from ...support.docker import MockDockerRegistry
from ..util import (
    create_ingress_for_user,
    create_working_ingress_for_user,
    delete_ingress_for_user,
)


@pytest.mark.asyncio
async def test_timeout_no_pod_start(
    mock_docker: MockDockerRegistry,
    mock_kubernetes: MockKubernetesApi,
    obj_factory: TestObjectFactory,
    config: Config,
    client: AsyncClient,
    std_result_dir: str,
) -> None:
    token, user = obj_factory.get_user()
    name = user.username
    namespace = config.fileserver.namespace
    save_initial = mock_kubernetes.initial_pod_phase
    save_fs_timeout = config.fileserver.creation_timeout
    # Set low for testing
    config.fileserver.creation_timeout = 1
    # The pod won't start on its own.
    mock_kubernetes.initial_pod_phase = "Pending"
    r = await client.get("/nublado/fileserver/v1/users")
    # No fileservers yet.
    assert r.json() == []
    #
    # Create an Ingress to match the GafaelfawrIngress.  In real
    # life, the GafaelfawrIngress creation would trigger this.
    await create_working_ingress_for_user(mock_kubernetes, name, namespace)
    # Start a user fileserver.  Expect a timeout, because the pod won't
    # start
    with pytest.raises(TimeoutError):
        r = await client.get(
            "/files",
            headers={
                "X-Auth-Request-User": name,
                "X-Auth-Request-Token": token,
            },
        )
    # Check that the fileserver user map is still clear
    r = await client.get("/nublado/fileserver/v1/users")
    assert r.json() == []
    # Set mock back to auto-start pods
    mock_kubernetes.initial_pod_phase = save_initial
    # Set creation timeout back to initial value
    config.fileserver.creation_timeout = save_fs_timeout
    # Clean up the Ingress
    await delete_ingress_for_user(mock_kubernetes, name, namespace)


@pytest.mark.asyncio
async def test_timeout_no_ingress(
    mock_docker: MockDockerRegistry,
    mock_kubernetes: MockKubernetesApi,
    obj_factory: TestObjectFactory,
    config: Config,
    client: AsyncClient,
    std_result_dir: str,
) -> None:
    token, user = obj_factory.get_user()
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
        r = await client.get(
            "/files",
            headers={
                "X-Auth-Request-User": user.username,
                "X-Auth-Request-Token": token,
            },
        )
    # Check that the fileserver user map is still clear
    r = await client.get("/nublado/fileserver/v1/users")
    assert r.json() == []
    # Set timeout back to initial value
    config.fileserver.creation_timeout = save_fs_timeout


@pytest.mark.asyncio
async def test_timeout_no_ingress_ip(
    mock_docker: MockDockerRegistry,
    mock_kubernetes: MockKubernetesApi,
    obj_factory: TestObjectFactory,
    config: Config,
    client: AsyncClient,
    std_result_dir: str,
) -> None:
    token, user = obj_factory.get_user()
    name = user.username
    namespace = config.fileserver.namespace
    save_fs_timeout = config.fileserver.creation_timeout
    # Set low for testing
    config.fileserver.creation_timeout = 1
    r = await client.get("/nublado/fileserver/v1/users")
    # No fileservers yet.
    assert r.json() == []

    async def create_fileserver() -> None:
        # Start a user fileserver.
        await client.get(
            "/files",
            headers={
                "X-Auth-Request-User": user.username,
                "X-Auth-Request-Token": token,
            },
        )

    # Start a user fileserver.  Expect a timeout, because the Ingress
    # did not get an IP address within the timeout.  This is a much
    # more realistic error, because the GafaelfawrIngress creates the
    # Ingress almost immediately but it often takes some time for the
    # ingress-nginx controller to get it correctly configured
    # Start the fileserver
    task = asyncio.create_task(create_fileserver())
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
