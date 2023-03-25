"""Routes for prepulling and available image information."""

from fastapi import APIRouter, Depends

from ..dependencies.context import RequestContext, context_dependency
from ..models.v1.prepuller import PrepullerStatus, SpawnerImages

router = APIRouter()
"""Router to mount into the application."""

__all__ = ["router"]


@router.get(
    "/spawner/v1/images", summary="Known images", response_model=SpawnerImages
)
async def get_images(
    context: RequestContext = Depends(context_dependency),
) -> SpawnerImages:
    return context.image_service.images()


@router.get(
    "/spawner/v1/prepulls",
    summary="Status of prepulling",
    response_model=PrepullerStatus,
    response_model_by_alias=False,
)
async def get_prepulls(
    context: RequestContext = Depends(context_dependency),
) -> PrepullerStatus:
    return context.image_service.prepull_status()
