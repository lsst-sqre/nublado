"""Tests for user lab routes."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient
from kubernetes_asyncio.client import (
    V1Ingress,
    V1LoadBalancerIngress,
    V1ObjectMeta,
)
from safir.testing.kubernetes import MockKubernetesApi

from jupyterlabcontroller.config import Config

from ...settings import TestObjectFactory
from ...support.docker import MockDockerRegistry


@pytest.mark.asyncio
async def test_fileserver(
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
    # Create an Ingress to match the GafaelfawrIngress.  In real
    # life, the GafaelfawrIngress creation would trigger this.
    await mock_kubernetes.create_namespaced_ingress(
        namespace=namespace,
        body=V1Ingress(
            metadata=V1ObjectMeta(name=f"{name}-fs", namespace=namespace)
        ),
    )
    # Patch the ingress so that it has an IP address
    t = await mock_kubernetes.patch_namespaced_ingress_status(
        f"{name}-fs",
        namespace,
        [
            {
                "op": "replace",
                "path": "/status/load_balancer/ingress",
                "value": [V1LoadBalancerIngress(ip="127.0.0.1")],
            }
        ],
    )
    print(f"***** {t} *******")
    # Start a user fileserver.
    r = await client.get(
        "/files",
        headers={
            "X-Auth-Request-User": user.username,
            "X-Auth-Request-Token": token,
        },
    )
    assert r.status_code == 200
    expected = Path(Path(std_result_dir) / "fileserver.txt").read_text()
    assert r.text == expected
    # Check that it has showed up, via an admin route.
    r = await client.get("/nublado/fileserver/v1/users")
    assert r.json() == [user.username]
    # Remove (by hand) the Ingress (again done automagically
    # in real life)
    await mock_kubernetes.delete_namespaced_ingress(
        name=f"{name}-fs", namespace=namespace
    )
    # Now remove it, again via an admin route
    r = await client.delete(f"/nublado/fileserver/v1/{user.username}")
    # Check that it's gone.
    r = await client.get("/nublado/fileserver/v1/users")
    assert r.json() == []
