"""User-facing routes, as defined in sqr-066 (https://sqr-066.lsst.io)
specifically for producing spawner forms"""
from fastapi import APIRouter, Depends, HTTPException
from safir.dependencies.logger import logger_dependency
from safir.models import ErrorModel
from structlog.stdlib import BoundLogger

from ..dependencies.context import context_dependency
from ..factory import Context

# FastAPI routers
router = APIRouter()

internal_router = APIRouter()

# Prefix: /nublado/spawner/v1/lab-form
#
# User routes
#
#
# Form handler
#


@router.get(
    "/{username}",
    summary="Get lab form for user",
    responses={
        403: {"description": "Forbidden", "model": ErrorModel},
    },
)
async def get_user_lab_form(
    username: str,
    context: Context = Depends(context_dependency),
    logger: BoundLogger = Depends(logger_dependency),
) -> str:
    """Get the lab creation form for a particular user."""
    user = await context.get_user()
    if user.username == "nobody":
        raise HTTPException(status_code=403, detail="Forbidden")
    token_username = user.username
    if token_username != username:
        raise HTTPException(status_code=403, detail="Forbidden")
    form_manager = context.form_manager
    return form_manager.generate_user_lab_form()
