"""Route handlers for control of migrator instance."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from safir.models import ErrorModel
from safir.slack.webhook import SlackRouteErrorHandler

from ..dependencies.context import RequestContext, context_dependency
from ..models.v1.migrator import MigratorCommand, MigratorStatus

router = APIRouter(route_class=SlackRouteErrorHandler)
"""Router to mount into the application."""

__all__ = ["router"]


@router.get(
    "/migrator/v1/service",
    responses={
        403: {
            "description": "Ownership change failed after copy",
            "model": ErrorModel,
        },
        404: {"description": "User not found", "model": ErrorModel},
        406: {"description": "File copy failed", "model": ErrorModel},
    },
    description=("Get the status of a user migration."),
    summary="Get migrator status",
    tags=["migrator"],
    status_code=200,
)
async def get_migrator_status(
    old_user: str,
    new_user: str,
    context: Annotated[RequestContext, Depends(context_dependency)],
    response: Response,
) -> MigratorStatus | None:
    st = await context.migrator_manager.get_status(old_user, new_user)
    if st is None:
        response.status_code = status.HTTP_204_NO_CONTENT
    return st


@router.post(
    "/migrator/v1/service",
    responses={
        403: {
            "description": "Ownership change failed after copy",
            "model": ErrorModel,
        },
        404: {"description": "User not found", "model": ErrorModel},
        406: {"description": "File copy failed", "model": ErrorModel},
    },
    description="Migrator is in progress if running is True.",
    summary="Query migrator instance",
    tags=["admin"],
    status_code=200,
)
async def create_migrator(
    *,
    cmd: MigratorCommand,
    context: Annotated[RequestContext, Depends(context_dependency)],
) -> MigratorStatus:
    return await context.migrator_manager.create(cmd.old_user, cmd.new_user)
