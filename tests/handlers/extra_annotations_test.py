import pytest
from httpx import AsyncClient
from safir.testing.kubernetes import MockKubernetesApi

from jupyterlabcontroller.dependencies.context import context_dependency

from ..settings import TestObjectFactory
from ..support.config import configure


@pytest.mark.asyncio
async def test_extra_annotations(
    client: AsyncClient,
    mock_kubernetes: MockKubernetesApi,
    obj_factory: TestObjectFactory,
) -> None:
    """Check that the pod picks up extra annotations set in the config."""
    token, user = obj_factory.get_user()
    lab = obj_factory.labspecs[0]

    # Reconfigure the app to add annotations
    await context_dependency.aclose()
    config = configure("extra-annotations")
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
    assert (
        pod.metadata.annotations["k8s.v1.cni.cncf.io/networks"]
        == "kube-system/dds"
    )
