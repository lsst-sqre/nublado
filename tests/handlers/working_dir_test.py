import pytest
from httpx import AsyncClient
from safir.testing.kubernetes import MockKubernetesApi

from jupyterlabcontroller.dependencies.context import context_dependency

from ..settings import TestObjectFactory
from ..support.config import configure


@pytest.mark.asyncio
async def test_pod_working_dir(
    client: AsyncClient,
    mock_kubernetes: MockKubernetesApi,
    obj_factory: TestObjectFactory,
) -> None:
    """Check that the pod working directory uses the right home directory.

    Earlier versions had a bug where the working directory for the spawned pod
    was always :file:`/home/{username}` even if another home directory rule
    was set.
    """
    token, user = obj_factory.get_user()
    lab = obj_factory.labspecs[0]

    # Reconfigure the app to use a different home directory scheme.
    await context_dependency.aclose()
    config = configure("homedir-schema")
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
    for container in pod.spec.containers:
        assert (
            container.working_dir
            == f"/home/{user.username[0]}/{user.username}"
        )
