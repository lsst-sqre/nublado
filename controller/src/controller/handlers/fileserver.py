"""Route handlers for administrative control of user file servers.

This does not include the route normally used by users to spawn a file server.
That route uses a separate path prefix and is defined in a different router in
`controller.handlers.files`.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from safir.models import ErrorModel
from safir.slack.webhook import SlackRouteErrorHandler

from ..dependencies.context import RequestContext, context_dependency
from ..exceptions import UnknownUserError

router = APIRouter(route_class=SlackRouteErrorHandler)
"""Router to mount into the application."""

__all__ = ["router"]


@router.get(
    "/fileserver/v1/users",
    responses={403: {"description": "Forbidden", "model": ErrorModel}},
    summary="List all users with running fileservers",
)
async def get_fileserver_users(
    context: Annotated[RequestContext, Depends(context_dependency)],
) -> list[str]:
    return await context.fileserver_manager.list()


@router.delete(
    "/fileserver/v1/{username}",
    responses={403: {"description": "Forbidden", "model": ErrorModel}},
    summary="Remove fileserver for user",
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
