"""Routes for prepulling and available image information."""

from typing import Annotated

from fastapi import APIRouter, Depends
from safir.slack.webhook import SlackRouteErrorHandler

from ..dependencies.context import RequestContext, context_dependency
from ..models.v1.prepuller import PrepullerStatus, SpawnerImages

router = APIRouter(route_class=SlackRouteErrorHandler)
"""Router to mount into the application."""

__all__ = ["router"]


@router.get(
    "/spawner/v1/images",
    summary="Known images",
    response_model_exclude_none=True,
    tags=["admin"],
)
async def get_images(
    context: Annotated[RequestContext, Depends(context_dependency)],
) -> SpawnerImages:
    return context.image_service.images()


@router.get(
    "/spawner/v1/prepulls",
    summary="Status of prepulling",
    response_model_by_alias=False,
    tags=["admin"],
)
async def get_prepulls(
    context: Annotated[RequestContext, Depends(context_dependency)],
) -> PrepullerStatus:
    return context.image_service.prepull_status()
