"""Handlers for the app's external root, ``/nublado/``."""

from typing import List

from fastapi import Depends
from safir.dependencies.logger import logger_dependency
from structlog.stdlib import BoundLogger

from ...models.image import Image
from ...models.prepull import Prepull
from .router import external_router

__all__ = ["get_images", "get_prepulls"]

# Prepuller API: https://sqr-066.lsst.io/#rest-api


@external_router.get(
    "/spawner/v1/images",
    summary="Get known images and their names",
)
async def get_images(
    logger: BoundLogger = Depends(logger_dependency),
) -> List[Image]:
    """Requires admin:notebook"""
    return []


@external_router.get(
    "/spawner/v1/prepulls",
    summary="Get status of prepull configurations",
)
async def get_prepulls(
    logger: BoundLogger = Depends(logger_dependency),
) -> List[Prepull]:
    """Requires admin:notebook"""
    return []
