"""Handlers for the app's external root, ``/nublado/``."""

from fastapi import Depends
from safir.dependencies.logger import logger_dependency
from structlog.stdlib import BoundLogger

from ...models.prepuller import PrepulledImageDisplayList, PrepullerStatus
from ...services.prepuller import get_current_image_and_node_state
from .router import external_router

__all__ = ["get_images", "get_prepulls"]

# Prepuller API: https://sqr-066.lsst.io/#rest-api


@external_router.get(
    "/spawner/v1/images",
    summary="Get known images and their names",
)
async def get_images(
    logger: BoundLogger = Depends(logger_dependency),
) -> PrepulledImageDisplayList:
    """Requires admin:notebook"""
    current_state, nodes = await get_current_image_and_node_state()
    return PrepulledImageDisplayList()


@external_router.get(
    "/spawner/v1/prepulls",
    summary="Get status of prepull configurations",
)
async def get_prepulls(
    logger: BoundLogger = Depends(logger_dependency),
) -> PrepullerStatus:
    """Requires admin:notebook"""
    return PrepullerStatus()
