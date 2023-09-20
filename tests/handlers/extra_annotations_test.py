import pytest
from httpx import AsyncClient
from safir.testing.kubernetes import MockKubernetesApi

from ..settings import TestObjectFactory
from ..support.config import configure


@pytest.mark.asyncio
async def test_extra_annotations(
    client: AsyncClient,
    mock_kubernetes: MockKubernetesApi,
    obj_factory: TestObjectFactory,
) -> None:
    """Check that the pod picks up extra annotations set in the config."""
    config = await configure("extra-annotations")
    token, user = obj_factory.get_user()
    lab = obj_factory.labspecs[0]

    r = await client.post(
        f"/nublado/spawner/v1/labs/{user.username}/create",
        json={"options": lab.options.model_dump(), "env": lab.env},
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
