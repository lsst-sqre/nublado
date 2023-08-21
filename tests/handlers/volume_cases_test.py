import pytest
from httpx import AsyncClient
from safir.testing.kubernetes import MockKubernetesApi

from jupyterlabcontroller.dependencies.context import context_dependency

from ..settings import TestObjectFactory
from ..support.config import configure


@pytest.mark.asyncio
async def test_volume_cases(
    client: AsyncClient,
    mock_kubernetes: MockKubernetesApi,
    obj_factory: TestObjectFactory,
) -> None:
    """Check that the pod picks up extra annotations set in the config."""
    token, user = obj_factory.get_user()
    lab = obj_factory.labspecs[0]

    # Reconfigure the app to add annotations
    await context_dependency.aclose()
    config = configure("volume-cases")
    await context_dependency.initialize(config)

    r = await client.post(
        f"/nublado/spawner/v1/labs/{user.username}/create",
        json={"options": lab.options.dict(), "env": lab.env},
        headers={
            "X-Auth-Request-Token": token,
            "X-Auth-Request-User": user.username,
        },
    )
    assert r.status_code == 201

    namespace = f"{config.lab.namespace_prefix}-{user.username}"
    pod_name = f"{user.username}-nb"
    pod = await mock_kubernetes.read_namespaced_pod(pod_name, namespace)
    ctr = pod.spec.containers[0]
    # lowercase works the same
    assert (
        ctr.volume_mounts[0].mount_path == "/home"
        and ctr.volume_mounts[0].name == "home"
    )
    # but upper and mixed-case are squashed to lower in object name
    assert (
        ctr.volume_mounts[1].mount_path == "/PROJECT"
        and ctr.volume_mounts[1].name == "project"
    )
    assert (
        ctr.volume_mounts[2].mount_path == "/ScRaTcH"
        and ctr.volume_mounts[2].name == "scratch"
    )
