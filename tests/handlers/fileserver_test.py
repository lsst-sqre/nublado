"""Tests for user lab routes."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient
from kubernetes_asyncio.client import V1Ingress, V1Namespace, V1ObjectMeta

from jupyterlabcontroller.factory import Factory

from ..settings import TestObjectFactory
from ..support.kubernetes import MockKubernetesApi


@pytest.mark.asyncio
async def test_fileserver(
    client: AsyncClient,
    std_result_dir: Path,
    factory: Factory,
    obj_factory: TestObjectFactory,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    token, user = obj_factory.get_user()
    name = user.username
    namespace = "fileservers"
    #
    # Create a namespace for fileserver objects.  This actually gets done
    # implicitly by the create_namespaced_ingress() below anyway, but let's
    # make it explicit.
    #
    await mock_kubernetes.create_namespace(
        V1Namespace(metadata=V1ObjectMeta(name=namespace))
    )
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
    assert r.status_code == 200
    expected = (std_result_dir / "fileserver.txt").read_text()
    assert r.text == expected
    # Check that it has showed up, via an admin route.
    r = await client.get("/nublado/fileserver/v1/users")
    assert r.json() == [user.username]
    # Remove (by hand) the Ingress (again done automagically in real life)
    await mock_kubernetes.delete_namespaced_ingress(
        name=f"{name}-fs", namespace=namespace
    )
    # Now remove it, again via an admin route
    r = await client.delete(f"/nublado/fileserver/v1/{user.username}")
    # Check that it's gone.
    r = await client.get("/nublado/fileserver/v1/users")
    assert r.json() == []
