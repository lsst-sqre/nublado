"""Routes for generating spawner forms."""

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import HTMLResponse
from safir.models import ErrorModel

from ..dependencies.context import RequestContext, context_dependency

router = APIRouter()
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
    x_auth_request_user: str = Header(...),
    context: RequestContext = Depends(context_dependency),
) -> str:
    if username != x_auth_request_user:
        raise HTTPException(status_code=403, detail="Forbidden")
    form_manager = context.factory.create_form_manager()
    return form_manager.generate_user_lab_form()
