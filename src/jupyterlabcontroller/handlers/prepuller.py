"""User-facing routes, as defined in sqr-066 (https://sqr-066.lsst.io)
specifically for the prepuller."""
from fastapi import APIRouter, Depends
from safir.models import ErrorModel

from ..dependencies.context import context_dependency
from ..models.context import Context
from ..models.v1.prepuller import PrepullerStatus, SpawnerImages

# FastAPI routers
router = APIRouter()


#
# Prepuller routes
#

# Prepuller API: https://sqr-066.lsst.io/#rest-api

# Prefix: /nublado/spawner/v1


@router.get(
    "/images",
    summary="Get known images and their names",
    responses={
        403: {"description": "Forbidden", "model": ErrorModel},
    },
    response_model=SpawnerImages,
)
async def get_images(
    context: Context = Depends(context_dependency),
) -> SpawnerImages:
    """Returns known images and their names."""
    return context.prepuller_arbitrator.get_spawner_images()


@router.get(
    "/prepulls",
    summary="Get status of prepull configurations",
    responses={
        403: {"description": "Forbidden", "model": ErrorModel},
    },
    response_model=PrepullerStatus,
)
async def get_prepulls(
    context: Context = Depends(context_dependency),
) -> PrepullerStatus:
    """Returns the list of known images and their names."""
    return context.prepuller_arbitrator.get_prepulls()
