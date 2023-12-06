"""Storage layer for Kubernetes node objects."""

from __future__ import annotations

from kubernetes_asyncio import client
from kubernetes_asyncio.client import ApiClient, ApiException
from structlog.stdlib import BoundLogger

from ...exceptions import KubernetesError
from ...models.domain.kubernetes import KubernetesNodeImage
from ...timeout import Timeout

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

    async def get_image_data(
        self, node_selector: dict[str, str], timeout: Timeout
    ) -> dict[str, list[KubernetesNodeImage]]:
        """Get the list of cached images from each node.

        Parameters
        ----------
        node_selector
            Node selector rules to restrict the list of nodes of interest.
        timeout
            Timeout for call.

        Returns
        -------
        dict of list
            Map of nodes to lists of all cached images on that node.
        """
        self._logger.debug(
            "Getting node image data", node_selector=node_selector
        )
        selector = None
        if node_selector:
            selector = ",".join(f"{k}={v}" for k, v in node_selector.items())
        try:
            nodes = await self._api.list_node(
                label_selector=selector, _request_timeout=timeout.left()
            )
        except ApiException as e:
            raise KubernetesError.from_exception(
                "Error reading node information", e, kind="Node"
            ) from e

        image_data = {}
        for node in nodes.items:
            if node.status is not None and node.status.images is not None:
                image_data[node.metadata.name] = [
                    KubernetesNodeImage.from_container_image(i)
                    for i in node.status.images
                ]
            else:
                image_data[node.metadata_name] = []
        return image_data
