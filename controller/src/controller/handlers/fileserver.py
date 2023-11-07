"""Rounte handlers for user file servers."""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from safir.models import ErrorModel
from safir.slack.webhook import SlackRouteErrorHandler

from ..config import Config
from ..constants import FILESERVER_TEMPLATE
from ..dependencies.config import configuration_dependency
from ..dependencies.context import RequestContext, context_dependency
from ..dependencies.user import user_dependency
from ..exceptions import UnknownUserError
from ..models.v1.lab import UserInfo
from ..util import seconds_to_phrase

router = APIRouter(route_class=SlackRouteErrorHandler)
user_router = APIRouter(route_class=SlackRouteErrorHandler)
"""Router to mount into the application."""

__all__ = ["router", "user_router"]

# This router does not go under the safir path prefix, but under its own,
# which by default is "" -- that is, user files are typically accessed as
# <base-url>/files
#
# Note that we don't care what's after /files.
#
# That's because the requesting user is identified by the header,
# and if there is already a more specific ingress path, then that
# ingress will handle the request and we will never see it.  That will be
# the case if the user already has a running fileserver, since
# /files/<username> will already be a (basic-auth) ingress for WebDAV.
#
# So either the user went to just "/files", in which case we figure
# out whether they need an ingress, and create it (and the backing
# fileserver) if so, or they went to "/files/<themselves>" but there
# is no ingress and backing fileserver, so we need to create it, or
# they went to "/files/<someone-else>" and there is no ingress for
# <someone-else>.  In the last case, we do exactly the same thing as
# for "/files": determine whether they themselves have a fileserver'
# and create it if it doesn't exist.
#
# In all these cases, we provide documentation of how to use the created
# fileserver.  This should eventually move into SquareOne and be nicely
# styled.
#
# Finally, if they go to "/files/<someone-else>" and there already
# is an ingress (that is, someone-else already has a running fileserver)
# then the user request will go there (and we will never see the request).
# In that case, it's not our problem; in any event, they won't have a token
# that lets them authenticate to WebDAV behind that ingress, so they can't
# do anything nefarious.


@user_router.get(
    "/files",
    summary="Allow user to access files, spawning new fileserver if needed.",
    responses={403: {"description": "Forbidden", "model": ErrorModel}},
    response_class=HTMLResponse,
)
async def route_user(
    context: RequestContext = Depends(context_dependency),
    config: Config = Depends(configuration_dependency),
    user: UserInfo = Depends(user_dependency),
) -> str:
    context.rebind_logger(user=user.username)
    try:
        await context.fileserver_manager.create(user)
    except Exception as e:
        # The exception was already reported to Slack at the service layer, so
        # convert it to a standard error message instead of letting it
        # propagate as an uncaught exception.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=[
                {
                    "msg": f"Failed to create file server: {e!s}",
                    "type": "file_server_create_failed",
                }
            ],
        ) from e
    return FILESERVER_TEMPLATE.format(
        username=user.username,
        base_url=config.base_url,
        timeout=seconds_to_phrase(config.fileserver.timeout),
    )


# The remaining endpoints are for administrative functions and can be
# tucked under the safir path prefix


@router.get(
    "/fileserver/v1/users",
    responses={403: {"description": "Forbidden", "model": ErrorModel}},
    summary="List all users with running fileservers",
)
async def get_fileserver_users(
    context: RequestContext = Depends(context_dependency),
) -> list[str]:
    return await context.fileserver_manager.list()


@router.delete(
    "/fileserver/v1/{username}",
    responses={403: {"description": "Forbidden", "model": ErrorModel}},
    summary="Remove fileserver for user",
)
async def remove_fileserver(
    username: str,
    context: RequestContext = Depends(context_dependency),
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
