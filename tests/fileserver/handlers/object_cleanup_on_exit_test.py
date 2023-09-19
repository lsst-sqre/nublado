"""Tests for user cleanup."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from httpx import AsyncClient
from kubernetes_asyncio.client import V1Pod
from safir.testing.kubernetes import MockKubernetesApi

from jupyterlabcontroller.config import Config
from jupyterlabcontroller.models.domain.kubernetes import PodPhase

from ...settings import TestObjectFactory
from ...support.docker import MockDockerRegistry
from ..util import create_working_ingress_for_user, delete_ingress_for_user


def _find_user_pod(user: str, objects: list[Any]) -> V1Pod:
    obj_name = f"{user}-fs"
    for obj in objects:
        if obj.kind == "Pod":
            for lbl in obj.metadata.labels:
                if lbl == "job-name" and obj.metadata.labels[lbl] == obj_name:
                    return obj
    raise AssertionError(f"Could not find pod for user {user}")


@pytest.mark.asyncio
async def test_cleanup_on_pod_exit(
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
    await create_working_ingress_for_user(mock_kubernetes, name, namespace)
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
    # Shut down the the pod, simulating timeout (in real life, the fileserver
    # takes the timeout as an argument and exits after it's been idle that
    # long, but that would require actually running the fileserver container;
    # it doesn't seem like there's much point in making the test suite wait
    # for an arbitrary timeout when what we really want to test is whether
    # shutting down the pod removes the fileserver).
    pod = _find_user_pod(
        user=user.username,
        objects=mock_kubernetes.get_namespace_objects_for_test(
            namespace=namespace
        ),
    )
    await mock_kubernetes.patch_namespaced_pod_status(
        name=pod.metadata.name,
        namespace="fileservers",
        body=[
            {
                "op": "replace",
                "path": "/status/phase",
                "value": PodPhase.SUCCEEDED.value,
            }
        ],
    )
    await asyncio.sleep(0.1)
    # Check that the fileserver user map is clear
    r = await client.get("/nublado/fileserver/v1/users")
    assert r.json() == []
    # Check that the fileserver objects have been deleted
    objs = mock_kubernetes.get_namespace_objects_for_test(namespace=namespace)
    # Note that namespace objects will still have the Ingress (because
    # the mock doesn't remove the ingress on GafaelfawrIngress
    # deletion like the real thing does), and will still have the
    # Namespace.  So let's check that.
    assert len(objs) == 2
    assert {x.kind for x in objs} == {"Ingress", "Namespace"}
    # Clean up the Ingress
    await delete_ingress_for_user(mock_kubernetes, name, namespace)
