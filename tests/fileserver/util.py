from kubernetes_asyncio.client import (
    V1Ingress,
    V1LoadBalancerIngress,
    V1ObjectMeta,
)
from safir.testing.kubernetes import MockKubernetesApi


async def create_ingress_for_user(
    mock_kubernetes: MockKubernetesApi, namespace: str, username: str
) -> None:
    # Create an Ingress to match the GafaelfawrIngress.  In real
    # life, the GafaelfawrIngress creation would trigger this.
    await mock_kubernetes.create_namespaced_ingress(
        namespace=namespace,
        body=V1Ingress(
            metadata=V1ObjectMeta(name=f"{username}-fs", namespace=namespace)
        ),
    )


async def activate_ingress_for_user(
    mock_kubernetes: MockKubernetesApi, namespace: str, username: str
) -> None:
    await mock_kubernetes.patch_namespaced_ingress_status(
        name=f"{username}-fs",
        namespace=namespace,
        body=[
            {
                "op": "replace",
                "path": "/status/loadBalancer/ingress",
                "value": [V1LoadBalancerIngress(ip="127.0.0.1")],
            }
        ],
    )


async def create_working_ingress_for_user(
    mock_kubernetes: MockKubernetesApi, namespace: str, username: str
) -> None:
    await create_ingress_for_user(mock_kubernetes, username, namespace)
    await activate_ingress_for_user(mock_kubernetes, username, namespace)


async def delete_ingress_for_user(
    mock_kubernetes: MockKubernetesApi,
    username: str,
    namespace: str,
) -> None:
    await mock_kubernetes.delete_namespaced_ingress(
        name=f"{username}-fs", namespace=namespace
    )
