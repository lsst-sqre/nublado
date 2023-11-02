"""Storage layer for Kubernetes node objects."""

from __future__ import annotations

from kubernetes_asyncio import client
from kubernetes_asyncio.client import ApiClient, ApiException
from structlog.stdlib import BoundLogger

from ...exceptions import KubernetesError
from ...models.domain.kubernetes import KubernetesNodeImage

__all__ = ["NodeStorage"]


class NodeStorage:
    """Storage layer for Kubernetes node objects.

    Parameters
    ----------
    api_client
        Kubernetes API client.
    logger
        Logger to use.
    """

    def __init__(self, api_client: ApiClient, logger: BoundLogger) -> None:
        self._api = client.CoreV1Api(api_client)
        self._logger = logger

    async def get_image_data(self) -> dict[str, list[KubernetesNodeImage]]:
        """Get the list of cached images from each node.

        Returns
        -------
        dict of list
            Map of nodes to lists of all cached images on that node.
        """
        self._logger.debug("Getting node image data")
        try:
            nodes = await self._api.list_node()
        except ApiException as e:
            raise KubernetesError.from_exception(
                "Error reading node information", e, kind="Node"
            ) from e

        image_data = {}
        for node in nodes.items:
            image_data[node.metadata.name] = [
                KubernetesNodeImage.from_container_image(i)
                for i in node.status.images
                if node.status is not None and node.status.images is not None
            ]
        return image_data
