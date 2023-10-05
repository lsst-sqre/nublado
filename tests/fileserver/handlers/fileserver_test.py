"""Tests for user lab routes."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from safir.testing.kubernetes import MockKubernetesApi

from jupyterlabcontroller.models.domain.gafaelfawr import GafaelfawrUser

from ...support.config import configure
from ...support.data import read_output_data
from ...support.docker import MockDockerRegistry
from ...support.fileserver import (
    create_working_ingress_for_user,
    delete_ingress_for_user,
)


@pytest.mark.asyncio
async def test_fileserver(
    client: AsyncClient,
    user: GafaelfawrUser,
    mock_docker: MockDockerRegistry,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    config = await configure("fileserver", mock_kubernetes)
    name = user.username
    namespace = config.fileserver.namespace
    r = await client.get("/nublado/fileserver/v1/users")
    # No fileservers yet.
    assert r.json() == []
    #
    # Create an Ingress to match the GafaelfawrIngress.  In real
    # life, the GafaelfawrIngress creation would trigger this.
    await create_working_ingress_for_user(mock_kubernetes, name, namespace)

    # Start a user fileserver.
    r = await client.get("/files", headers=user.to_headers())
    assert r.status_code == 200
    expected = read_output_data("fileserver", "fileserver.txt")
    assert r.text == expected
    # Check that it has showed up, via an admin route.
    r = await client.get("/nublado/fileserver/v1/users")
    assert r.json() == [user.username]
    #
    # Request it again; should detect that there is a user fileserver and
    # return immediately without actually doing anything.
    #
    r = await client.get("/files", headers=user.to_headers())
    assert r.status_code == 200
    assert r.text == expected
    # Make sure fileserver still exists
    r = await client.get("/nublado/fileserver/v1/users")
    assert r.json() == [name]

    # Remove (by hand) the Ingress (again done automagically
    # in real life)
    await delete_ingress_for_user(mock_kubernetes, name, namespace)
    # Now remove it, again via an admin route
    r = await client.delete(f"/nublado/fileserver/v1/{name}")
    # Check that it's gone.
    r = await client.get("/nublado/fileserver/v1/users")
    assert r.json() == []
