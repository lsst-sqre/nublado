"""Storage layer for Kubernetes node objects."""

from __future__ import annotations

from kubernetes_asyncio import client
from kubernetes_asyncio.client import ApiClient, ApiException, V1Node, V1Taint
from structlog.stdlib import BoundLogger

from ...exceptions import KubernetesError
from ...models.domain.kubernetes import (
    KubernetesNodeImage,
    NodeToleration,
    Toleration,
    TolerationOperator,
)
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

    def get_cached_images(
        self, nodes: list[V1Node]
    ) -> dict[str, list[KubernetesNodeImage]]:
        """Build map of what images are cached on each node.

        Parameters
        ----------
        nodes
            List of Kubernetes nodes with their metadata.

        Returns
        -------
        dict of list
            Mapping of node names to lists of cached images on that node.
        """
        image_data = {}
        for node in nodes:
            if node.status and node.status.images:
                image_data[node.metadata.name] = [
                    KubernetesNodeImage.from_container_image(i)
                    for i in node.status.images
                ]
            else:
                image_data[node.metadata.name] = []
        return image_data

    def is_tolerated(
        self, node: V1Node, tolerations: list[Toleration]
    ) -> NodeToleration:
        """Determine whether a pod can be placed on a node.

        Evaluates the node taints against the provided tolerations and
        determines whether an image with those tolerations can be placed on
        that node. Nodes with a ``PreferNoSchedule`` taint are still
        tolerated.

        Parameters
        ----------
        node
            Kubernetes node.
        tolerations
            List of tolerations that the pod will have.

        Returns
        -------
        NodeToleration
            Information about whether that image can be placed on that node.
        """
        # If there are no taints, the node is always tolerated.
        if not node.spec or not node.spec.taints:
            return NodeToleration(eligible=True)

        # Walk through each taint in turn and compare to the tolerations.
        # Ignore PreferNoSchedule taints, since they can't make the node not
        # tolerated.
        for taint in node.spec.taints:
            if taint.effect == "PreferNoSchedule":
                continue
            tolerated = False
            for toleration in tolerations:
                tolerated = self._toleration_matches(taint, toleration)
                if tolerated:
                    break

            # If this taint was not tolerated, return the result with an
            # explanation of the taint. This means we only report the first
            # taint that is not tolerated.
            if not tolerated:
                comment = f"Node is tainted ({taint.effect}, "
                if taint.value:
                    comment += f"{taint.key} = {taint.value})"
                else:
                    comment += f"{taint.key})"
                return NodeToleration(eligible=False, comment=comment)

        # If this point was reached, all taints were tolerated.
        return NodeToleration(eligible=True)

    async def list(
        self, node_selector: dict[str, str], timeout: Timeout
    ) -> list[V1Node]:
        """Get data about Kubernetes nodes.

        Parameters
        ----------
        node_selector
            Node selector rules to restrict the list of nodes of interest.
        timeout
            Timeout for call.

        Returns
        -------
        list of kubernetes_asyncio.client.models.V1Node
            List of node metadata.
        """
        self._logger.debug("Getting node data", node_selector=node_selector)
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
        return nodes.items

    def _toleration_matches(
        self, taint: V1Taint, toleration: Toleration
    ) -> bool:
        """Whether a given toleration matches a taint.

        Parameters
        ----------
        taint
            Taint on a node.
        toleration
            Toleration to check.

        Returns
        -------
        bool
            `True` if that toleration matches the taint with no expiration
            time, `False` otherwise.
        """
        # Tolerations must have a matching effect if specified to have any
        # effect.
        if toleration.effect and toleration.effect.value != taint.effect:
            return False

        # Temporary tolerations are ignored for the purposes of deciding if
        # the node is tolerated, since we don't want to prepull to a node on
        # the basis of a temporary toleration.  It's safe to skip a prepull
        # cycle on that node; if the taint is removed, we'll catch it on the
        # next cycle.
        if toleration.toleration_seconds is not None:
            if taint.effect == "NoExecute":
                return False

        # Check if this toleration matches the taint.
        match toleration.operator:
            case TolerationOperator.EXISTS:
                return taint.key == toleration.key if toleration.key else True
            case TolerationOperator.EQUAL:
                return (
                    taint.key == toleration.key
                    and taint.value == toleration.value
                )
