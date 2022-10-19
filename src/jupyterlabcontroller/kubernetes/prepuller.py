"""Prepull images to nodes.  This requires node inspection and a DaemonSet.
"""
import asyncio
from typing import Any, Dict, List

from fastapi import Depends
from kubernetes_asyncio.client import api_client
from kubernetes_asyncio.client.models import V1ContainerImage
from safir.dependencies.logger import logger_dependency
from structlog.stdlib import BoundLogger

from ..dependencies.k8s_corev1_api import corev1_api_dependency
from ..models.prepuller import Config
from ..runtime.config import controller_config

NodeContainers = Dict[str, List[V1ContainerImage]]


async def _load_config() -> List[Config]:
    r: List[Config] = []
    prepuller_config_obj: List[Any] = controller_config["prepuller"]["configs"]
    for c_o in prepuller_config_obj:
        r.append(Config(**c_o))
    return r


async def get_current_image_state(
    logger: BoundLogger = Depends(logger_dependency),
    api: api_client = Depends(corev1_api_dependency),
) -> None:
    logger.debug("Listing nodes and their image contents.")
    resp = await api.list_node()
    all_images_by_node: NodeContainers = {}
    for n in resp.items:
        nn = n.metadata.name
        all_images_by_node[nn] = n.images.copy()
    logger.debug(f"All images on nodes: {all_images_by_node}")

    configs: List[Config] = await _load_config()
    configtasks: List[asyncio.Task] = []
    for c in configs:
        task = asyncio.create_task(_imgs_for_config(c, all_images_by_node))
        configtasks.append(task)
    r: List[NodeContainers] = await (asyncio.gather(*configtasks))
    _ = r  # FIXME


async def _imgs_for_config(
    c: Config, all_images_by_node: NodeContainers
) -> None:
    config_images = _filter_images(all_images_by_node)
    _ = config_images  # FIXME


def _filter_images(images: NodeContainers) -> NodeContainers:
    return images
