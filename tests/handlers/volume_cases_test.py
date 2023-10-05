"""Test case of volumes."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from safir.testing.kubernetes import MockKubernetesApi

from jupyterlabcontroller.models.domain.gafaelfawr import GafaelfawrUser

from ..support.config import configure
from ..support.data import read_input_lab_specification_json


@pytest.mark.asyncio
async def test_volume_cases(
    client: AsyncClient,
    user: GafaelfawrUser,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    config = await configure("volume-cases")
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
    ctr = pod.spec.containers[0]
    # lowercase works the same
    assert ctr.volume_mounts[0].mount_path == "/home"
    assert ctr.volume_mounts[0].name == "home"
    # but upper and mixed-case are squashed to lower in object name
    assert ctr.volume_mounts[1].mount_path == "/PROJECT"
    assert ctr.volume_mounts[1].name == "project"
    assert ctr.volume_mounts[2].mount_path == "/ScRaTcH"
    assert ctr.volume_mounts[2].name == "scratch"
