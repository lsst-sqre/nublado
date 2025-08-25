"""Route handlers for administrative control of fsadmin instance."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
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
        "On successful return (a 204), the fsadmin instance is operational."
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
    if start_time := await context.fsadmin_manager.get_start_time():
        return FSAdminStatus(start_time=start_time)
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=[
            {
                "msg": "fsadmin instance not found or not ready",
                "type": "fsadmin_not_ready",
            }
        ],
    )


@router.post(
    "/fsadmin/v1/service",
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
    _ = cmd
    start_time = await context.fsadmin_manager.create()
    return FSAdminStatus(start_time=start_time)


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
    try:
        await context.fsadmin_manager.delete()
    except Exception as e:
        # The exception was already reported to Slack at the service layer, so
        # convert it to a standard error message instead of letting it
        # propagate as an uncaught exception.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=[
                {
                    "msg": f"Failed to delete fsadmin: {e!s}",
                    "type": "fsadmin_delete_failed",
                }
            ],
        ) from e
