"""User-facing routes that otherwise require a JupyterHub token."""

from fastapi import APIRouter, Depends, Header
from safir.models import ErrorModel
from safir.slack.webhook import SlackRouteErrorHandler

from ..dependencies.context import RequestContext, context_dependency
from ..exceptions import UnknownUserError
from ..models.v1.lab import UserData

router = APIRouter(route_class=SlackRouteErrorHandler)
"""Router to mount into the application."""

__all__ = ["router"]


@router.get(
    "/spawner/v1/user-status",
    responses={404: {"description": "Lab not found", "model": ErrorModel}},
    summary="Status of user's lab",
    response_model=UserData,
)
async def get_user_status(
    x_auth_request_user: str = Header(..., include_in_schema=False),
    context: RequestContext = Depends(context_dependency),
) -> UserData:
    context.rebind_logger(user=x_auth_request_user)
    userdata = context.user_map.get(x_auth_request_user)
    if userdata is None:
        raise UnknownUserError(f"Unknown user {x_auth_request_user}")
    return userdata
