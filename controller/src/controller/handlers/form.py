"""Routes for generating spawner forms."""

from fastapi import APIRouter, Depends, Header
from fastapi.responses import HTMLResponse
from safir.models import ErrorModel
from safir.slack.webhook import SlackRouteErrorHandler

from ..dependencies.context import RequestContext, context_dependency
from ..exceptions import PermissionDeniedError

router = APIRouter(route_class=SlackRouteErrorHandler)
"""Router to mount into the application."""

__all__ = ["router"]


@router.get(
    "/spawner/v1/lab-form/{username}",
    summary="Get lab form for user",
    response_class=HTMLResponse,
    responses={403: {"description": "Forbidden", "model": ErrorModel}},
)
async def get_user_lab_form(
    username: str,
    x_auth_request_user: str = Header(..., include_in_schema=False),
    context: RequestContext = Depends(context_dependency),
) -> str:
    if username != x_auth_request_user:
        raise PermissionDeniedError("Permission denied")
    form_manager = context.factory.create_form_manager()
    return form_manager.generate_user_lab_form()
