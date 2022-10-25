from typing import Optional

from fastapi import Depends
from kubernetes_asyncio import client
from kubernetes_asyncio.client.api_client import ApiClient


class K8sAPIDependency:
    """Provides an ``asyncio.clients.api_client.ApiClient`` dependency."""

    def __init__(self) -> None:
        self.api: Optional[ApiClient] = None

    async def __call__(self) -> ApiClient:
        if not self.api:
            self.api = ApiClient()
        return self.api

    async def aclose(self) -> None:
        if self.api:
            await self.api.close()


k8s_api_dependency = K8sAPIDependency()
"""The dependency that will return the K8s generic async client."""


class K8sCoreV1ApiDependency:
    async def __call__(
        self, api: ApiClient = Depends(k8s_api_dependency)
    ) -> client.CoreV1Api:
        return client.CoreV1Api(api)


"""The dependency that will return the K8s CoreV1API client."""
k8s_corev1api_dependency = K8sCoreV1ApiDependency()
