"""User-facing routes that otherwise require a JupyterHub token."""

from fastapi import APIRouter, Depends, Header, HTTPException
from safir.models import ErrorModel

from ..dependencies.context import RequestContext, context_dependency
from ..models.v1.lab import UserData

router = APIRouter()
"""Router to mount into the application."""

__all__ = ["router"]


@router.get(
    "/spawner/v1/user-status",
    responses={404: {"description": "Lab not found", "model": ErrorModel}},
    summary="Status of user's lab",
    response_model=UserData,
)
async def get_user_status(
    x_auth_request_user: str = Header(...),
    context: RequestContext = Depends(context_dependency),
) -> UserData:
    userdata = context.user_map.get(x_auth_request_user)
    if userdata is None:
        raise HTTPException(status_code=404, detail="Not found")
    return userdata
