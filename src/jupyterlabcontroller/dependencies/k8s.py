from typing import Optional

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
