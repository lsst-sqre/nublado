"""Tests for user cleanup."""

from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient
from safir.testing.kubernetes import MockKubernetesApi

from jupyterlabcontroller.config import Config

from ...settings import TestObjectFactory
from ...support.docker import MockDockerRegistry
from ..util import create_working_ingress_for_user, delete_ingress_for_user


@pytest.mark.asyncio
async def test_wait_for_ingress(
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
    r = await client.get("/nublado/fileserver/v1/users")
    # No fileservers yet.
    assert r.json() == []

    #
    async def create_fileserver() -> None:
        # Start a user fileserver.
        r = await client.get(
            "/files",
            headers={
                "X-Auth-Request-User": user.username,
                "X-Auth-Request-Token": token,
            },
        )
        assert r.status_code == 200
        # Check that it has showed up, via an admin route.
        r = await client.get("/nublado/fileserver/v1/users")
        assert r.json() == [user.username]

    # Start the fileserver
    task = asyncio.create_task(create_fileserver())
    # Check that task is running
    assert task.done() is False
    # Check there are no fileservers yet.
    r = await client.get("/nublado/fileserver/v1/users")
    assert r.json() == []

    # Create the Ingress
    await create_working_ingress_for_user(mock_kubernetes, name, namespace)

    # Now the task will complete and we will have a fileserver
    await task
    assert task.done() is True

    r = await client.get("/nublado/fileserver/v1/users")
    assert r.json() == [user.username]

    # Now remove fileserver
    r = await client.delete(f"/nublado/fileserver/v1/{user.username}")
    # Check that it's gone.
    r = await client.get("/nublado/fileserver/v1/users")
    assert r.json() == []

    # Clean up the Ingress
    await delete_ingress_for_user(mock_kubernetes, name, namespace)
