"""User-facing routes that otherwise require a JupyterHub token."""

from fastapi import APIRouter, Depends, Header
from safir.models import ErrorModel
from safir.slack.webhook import SlackRouteErrorHandler

from ..dependencies.context import RequestContext, context_dependency
from ..models.v1.lab import UserLabState

router = APIRouter(route_class=SlackRouteErrorHandler)
"""Router to mount into the application."""

__all__ = ["router"]


@router.get(
    "/spawner/v1/user-status",
    responses={404: {"description": "Lab not found", "model": ErrorModel}},
    summary="Status of user's lab",
    response_model=UserLabState,
)
async def get_user_state(
    x_auth_request_user: str = Header(..., include_in_schema=False),
    context: RequestContext = Depends(context_dependency),
) -> UserLabState:
    context.rebind_logger(user=x_auth_request_user)
    return await context.lab_state.get_lab_state(x_auth_request_user)
