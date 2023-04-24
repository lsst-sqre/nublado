"""Tests for user lab routes."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from kubernetes_asyncio.client import V1Ingress, V1ObjectMeta

from jupyterlabcontroller.factory import Factory

from ..settings import TestObjectFactory
from ..support.kubernetes import MockKubernetesApi


@pytest.mark.asyncio
async def test_fileserver_start(
    client: AsyncClient,
    factory: Factory,
    obj_factory: TestObjectFactory,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    token, user = obj_factory.get_user()
    name = user.username
    namespace = "fileservers"
    r = await client.get("/nublado/fileserver/v1/users")
    # No fileservers yet.
    assert r.json() == []
    #
    # Create an Ingress to match the GafaelfawrIngress.  In real life,
    # the GafaelfawrIngress creation would trigger this.
    await mock_kubernetes.create_namespaced_ingress(
        namespace=namespace,
        body=V1Ingress(
            metadata=V1ObjectMeta(name=f"{name}-fs", namespace=namespace)
        ),
    )
    # Start a user fileserver.
    r = await client.get(
        "/files",
        headers={
            "X-Auth-Request-User": user.username,
            "X-Auth-Request-Token": token,
        },
    )
    assert r.status_code == 307
    assert r.headers.get("location") == f"/files/{user.username}"
    # Check that it has showed up.
    r = await client.get("/nublado/fileserver/v1/users")
    assert r.json() == [user.username]
    # Now remove it
    r = await client.delete(f"/nublado/fileserver/v1/{user.username}")
    # And remove (by hand) the Ingress (again done automagically in real life)
    await mock_kubernetes.delete_namespaced_ingress(
        name=f"{name}-fs", namespace=namespace
    )
    # Check that it's gone.
    r = await client.get("/nublado/fileserver/v1/users")
    assert r.json() == []
