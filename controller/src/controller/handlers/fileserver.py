"""Route handlers for administrative control of user file servers.

This does not include the route normally used by users to spawn a file server.
That route uses a separate path prefix and is defined in a different router in
`controller.handlers.files`.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status, Header
from safir.models import ErrorModel
from safir.slack.webhook import SlackRouteErrorHandler

from ..dependencies.context import RequestContext, context_dependency
from ..exceptions import UnknownUserError
from ..models.v1.fileserver import FileserverStatus

router = APIRouter(route_class=SlackRouteErrorHandler)
"""Router to mount into the application."""

__all__ = ["router"]


@router.get(
    "/fileserver/v1/users",
    responses={403: {"description": "Forbidden", "model": ErrorModel}},
    summary="List all users with running fileservers",
    tags=["admin"],
)
async def get_fileserver_users(
    context: Annotated[RequestContext, Depends(context_dependency)],
) -> list[str]:
    return await context.fileserver_manager.list()


@router.get(
    "/fileserver/v1/users/{username}",
    responses={
        404: {"description": "File server not running", "model": ErrorModel}
    },
    summary="Status of file server",
    description=(
        "On successful return, running will always be true. If the file server"
        " is not running, a 404 error will be returned, since the file server"
        " resource does not exist."
    ),
    response_model=FileserverStatus,
    tags=["admin"],
)
async def get_fileserver_status(
    username: str,
    context: Annotated[RequestContext, Depends(context_dependency)],
) -> FileserverStatus:
    status = context.fileserver_manager.get_status(username)
    if not status.running:
        raise UnknownUserError("No file server running")
    return status


@router.delete(
    "/fileserver/v1/users/{username}",
    responses={403: {"description": "Forbidden", "model": ErrorModel}},
    status_code=204,
    summary="Remove fileserver for user",
    tags=["admin"],
)
async def remove_fileserver(
    username: str,
    context: Annotated[RequestContext, Depends(context_dependency)],
) -> None:
    context.rebind_logger(user=username)
    try:
        await context.fileserver_manager.delete(username)
    except UnknownUserError:
        raise
    except Exception as e:
        # The exception was already reported to Slack at the service layer, so
        # convert it to a standard error message instead of letting it
        # propagate as an uncaught exception.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=[
                {
                    "msg": f"Failed to delete file server: {e!s}",
                    "type": "file_server_delete_failed",
                }
            ],
        ) from e


@router.get(
    "/fileserver/v1/user-status",
    responses={
        404: {"description": "File server not running", "model": ErrorModel}
    },
    summary="State of user's file server",
    description=(
        "On successful return, running will always be true. If the file server"
        " is not running, a 404 error will be returned. This is consistent"
        " with the admin endpoint and allows clients to look at the HTTP"
        " status code without parsing the body."
    ),
    response_model=FileserverStatus,
    tags=["user"],
)
async def get_user_state(
    x_auth_request_user: Annotated[str, Header(include_in_schema=False)],
    context: Annotated[RequestContext, Depends(context_dependency)],
) -> FileserverStatus:
    status = context.fileserver_manager.get_status(x_auth_request_user)
    if not status.running:
        raise UnknownUserError("No file server running")
    return status
