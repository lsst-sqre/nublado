from kubernetes_asyncio.client import api_client

from ..kubernetes.client import shared_client


class CoreV1APIDependency:
    """Provides an ``asyncio.clients.api_client`` dependency; this one is
    configured as a CoreV1API client, which is the one you will use the most
    often.  It is given by ``..kubernetes.client.api_client`` so it is
    actually a singleton.
    """

    async def __call__(self) -> api_client:
        return shared_client("CoreV1Api")


corev1_api_dependency = CoreV1APIDependency()
"""The dependency that will return the K8s CoreV1API client."""
