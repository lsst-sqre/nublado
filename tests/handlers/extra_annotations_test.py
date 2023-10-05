"""Tests for adding extra annotations to lab pods."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from safir.testing.kubernetes import MockKubernetesApi

from jupyterlabcontroller.models.domain.gafaelfawr import GafaelfawrUser

from ..support.config import configure
from ..support.data import read_input_lab_specification_json


@pytest.mark.asyncio
async def test_extra_annotations(
    client: AsyncClient,
    user: GafaelfawrUser,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    """Check that the pod picks up extra annotations set in the config."""
    config = await configure("extra-annotations")
    lab = read_input_lab_specification_json("base", "lab-specification.json")

    r = await client.post(
        f"/nublado/spawner/v1/labs/{user.username}/create",
        json={"options": lab.options.model_dump(), "env": lab.env},
        headers={
            "X-Auth-Request-Token": user.token,
            "X-Auth-Request-User": user.username,
        },
    )
    assert r.status_code == 201

    namespace = f"{config.lab.namespace_prefix}-{user.username}"
    pod_name = f"{user.username}-nb"
    pod = await mock_kubernetes.read_namespaced_pod(pod_name, namespace)
    assert (
        pod.metadata.annotations["k8s.v1.cni.cncf.io/networks"]
        == "kube-system/dds"
    )
