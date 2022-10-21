"""Prepull images to nodes.  This requires node inspection and a DaemonSet.
"""
from copy import copy
from typing import Dict, List

from fastapi import Depends
from kubernetes_asyncio.client import api_client
from kubernetes_asyncio.client.models import V1ContainerImage
from safir.dependencies.logger import logger_dependency
from structlog.stdlib import BoundLogger

from ..dependencies.k8s_corev1_api import corev1_api_dependency

NodeContainers = Dict[str, List[V1ContainerImage]]


async def get_image_data_from_k8s(
    logger: BoundLogger = Depends(logger_dependency),
    api: api_client = Depends(corev1_api_dependency),
) -> NodeContainers:
    logger.debug("Listing nodes and their image contents.")
    resp = await api.list_node()
    all_images_by_node: NodeContainers = {}
    for n in resp.items:
        nn = n.metadata.name
        all_images_by_node[nn] = []
        for ci in n.status.images:
            all_images_by_node[nn].append(copy(ci))
    logger.debug(f"All images on nodes: {all_images_by_node}")
    return all_images_by_node
