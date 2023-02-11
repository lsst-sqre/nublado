"""User-facing routes, as defined in sqr-066 (https://sqr-066.lsst.io),
to determine user status"""
from fastapi import APIRouter, Depends, Header, HTTPException
from safir.models import ErrorModel

from ..dependencies.context import RequestContext, context_dependency
from ..models.v1.lab import UserData

# FastAPI routers
router = APIRouter()


#
# User routes
#


# Lab Controller API: https://sqr-066.lsst.io/#lab-controller-rest-api
# Prefix: /nublado/spawner/v1/user-status


@router.get(
    "",
    responses={
        404: {"description": "Lab not found", "model": ErrorModel},
        403: {"description": "Forbidden", "model": ErrorModel},
    },
    summary="Get status for user",
    response_model=UserData,
)
async def get_user_status(
    x_auth_request_user: str = Header(...),
    context: RequestContext = Depends(context_dependency),
) -> UserData:
    """Get the pod status for the authenticating user."""
    userdata = context.user_map.get(x_auth_request_user)
    if userdata is None:
        raise HTTPException(status_code=404, detail="Not found")
    return userdata
