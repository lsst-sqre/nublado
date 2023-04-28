from fastapi import APIRouter, Depends, Header
from fastapi.responses import HTMLResponse
from safir.models import ErrorModel
from safir.slack.webhook import SlackRouteErrorHandler

from ..config import Config
from ..constants import FILESERVER_TEMPLATE
from ..dependencies.config import configuration_dependency
from ..dependencies.context import RequestContext, context_dependency
from ..exceptions import FileserverCreationError, PermissionDeniedError

router = APIRouter(route_class=SlackRouteErrorHandler)
user_router = APIRouter(route_class=SlackRouteErrorHandler)
"""Router to mount into the application."""

__all__ = ["router", "user_router"]

# This router is really at the top level--there's no safir path prefix.


@user_router.get(
    "/files",
    summary="Allow user to access files, spawning new fileserver if needed.",
    responses={403: {"description": "Forbidden", "model": ErrorModel}},
    response_class=HTMLResponse,
)
async def route_user(
    context: RequestContext = Depends(context_dependency),
    config: Config = Depends(configuration_dependency),
    x_auth_request_user: str = Header(..., include_in_schema=False),
    x_auth_request_token: str = Header(..., include_in_schema=False),
) -> str:
    """Note that we don't care what's after /files.

    That's because the requesting user is identified by the header,
    and if there is already a more specific ingress path, then that
    ingress will handle the request and we will never see it.

    So either the user went to just "/files", in which case we figure
    out whether they need an ingress, and create it (and the backing
    fileserver) if so, or they went to "/files/<themselves>" but there
    is no ingress and backing fileserver, so we need to create it, or
    they went to "/files/<someone-else>" and there is no ingress for
    <someone-else>.  In the last case, we determine whether they
    themselves have a fileserver and create it if it doesn't exist.

    In all these cases, we provide documentation of how to use the created
    fileserver.  This should eventually move into SquareOne and be nicely
    styled.

    Finally, if they go to "/files/<someone-else>" and there already
    is an ingress then they will go there (and we will never see the
    request), but they won't have a token that lets them authenticate
    to WebDAV with it, so they can't do anything nefarious.
    """
    username = x_auth_request_user
    gafaelfawr_client = context.factory.create_gafaelfawr_client()
    user = await gafaelfawr_client.get_user_info(x_auth_request_token)
    if user.username != username:
        raise PermissionDeniedError("Permission denied")
    # The user is valid.  Create a fileserver for them (or use an extant
    # one)
    context.rebind_logger(user=username)
    fileserver_state = context.fileserver_state
    timeout = config.fileserver.timeout
    base_url = config.base_url
    result = await fileserver_state.create(user)
    if result:
        return FILESERVER_TEMPLATE.format(
            username=user.username, base_url=base_url, timeout=timeout
        )
    raise FileserverCreationError("Error creating fileserver")


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
    return await context.fileserver_state.list()


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
    await context.fileserver_state.delete(username)