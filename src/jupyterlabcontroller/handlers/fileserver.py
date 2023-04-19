from fastapi import APIRouter, Depends, Header
from fastapi.responses import RedirectResponse
from safir.slack.webhook import SlackRouteErrorHandler

from ..dependencies.context import RequestContext, context_dependency

router = APIRouter(route_class=SlackRouteErrorHandler)
"""Router to mount into the application."""

__all__ = ["router"]


@router.get(
    "/files",
    summary="Allow user to access files, spawning new fileserver if needed.",
    response_class=RedirectResponse,
)
async def route_user(
    context: RequestContext = Depends(context_dependency),
    x_auth_request_user: str = Header(..., include_in_schema=False),
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

    In all these cases, we provide a redirect to their own fileserver
    endpoint.

    Finally, if they go to "/files/<someone-else>" and there already
    is an ingress then they will go there (and we will never see the
    request), but they won't have a token that lets them authenticate
    to WebDAV with it, so they can't do anything nefarious.
    """
    username = x_auth_request_user

    return f"/files/{username}"
