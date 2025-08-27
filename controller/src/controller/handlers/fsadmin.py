"""Route handlers for administrative control of fsadmin instance."""

from typing import Annotated

from fastapi import APIRouter, Depends
from safir.models import ErrorModel
from safir.slack.webhook import SlackRouteErrorHandler

from ..dependencies.context import RequestContext, context_dependency
from ..models.v1.fsadmin import FSAdminCommand, FSAdminStatus

router = APIRouter(route_class=SlackRouteErrorHandler)
"""Router to mount into the application."""

__all__ = ["router"]


@router.get(
    "/fsadmin/v1/service",
    responses={
        404: {
            "description": "Filesystem admin instance not running",
            "model": ErrorModel,
        },
    },
    description=(
        "On successful return, the fsadmin instance is operational."
        " If it does not exist or is not running, a 404 error will be "
        " returned."
    ),
    summary="Get fsadmin status",
    tags=["admin"],
    status_code=200,
)
async def get_fsadmin_status(
    context: Annotated[RequestContext, Depends(context_dependency)],
) -> FSAdminStatus:
    return await context.fsadmin_manager.get_status()


@router.post(
    "/fsadmin/v1/service",
    responses={
        404: {
            "description": "Filesystem admin instance not running",
            "model": ErrorModel,
        },
    },
    description="On successful return, the fsadmin instance is operational.",
    summary="Create fsadmin instance",
    tags=["admin"],
    status_code=200,
)
async def create_fsadmin(
    *,
    cmd: FSAdminCommand,
    context: Annotated[RequestContext, Depends(context_dependency)],
) -> FSAdminStatus:
    return await context.fsadmin_manager.create()


@router.delete(
    "/fsadmin/v1/service",
    description="On successful return, the fsadmin instance does not exist.",
    summary="Remove fsadmin instance",
    tags=["admin"],
    status_code=204,
)
async def remove_fsadmin(
    context: Annotated[RequestContext, Depends(context_dependency)],
) -> None:
    await context.fsadmin_manager.delete()
