"""User-facing routes, as defined in sqr-066 (https://sqr-066.lsst.io),
these specifically for lab manipulation"""
import os
from typing import List

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from safir.models import ErrorModel
from sse_starlette import EventSourceResponse

from ..dependencies.context import RequestContext, context_dependency
from ..exceptions import InvalidUserError, LabExistsError, NoUserMapError
from ..models.v1.lab import LabSpecification, UserData


def _external_url() -> str:
    return os.environ.get("EXTERNAL_INSTANCE_URL", "http://localhost:8080")


# FastAPI routers
router = APIRouter()


#
# User routes
#


# Lab Controller API: https://sqr-066.lsst.io/#lab-controller-rest-api
# Prefix: /nublado/spawner/v1/labs


@router.get(
    "",
    responses={
        403: {"description": "Forbidden", "model": ErrorModel},
    },
    summary="List all users with running labs",
)
async def get_lab_users(
    context: RequestContext = Depends(context_dependency),
) -> List[str]:
    """Returns a list of all users with running labs."""
    return await context.user_map.running()


@router.get(
    "/{username}",
    response_model=UserData,
    responses={
        404: {"description": "Lab not found", "model": ErrorModel},
        403: {"description": "Forbidden", "model": ErrorModel},
    },
    summary="Status of user",
)
async def get_userdata(
    username: str,
    context: RequestContext = Depends(context_dependency),
) -> UserData:
    """Returns status of the lab pod for the given user."""
    userdata = context.user_map.get(username)
    if userdata is None:
        raise HTTPException(status_code=404, detail="Not found")
    return userdata


@router.post(
    "/{username}/create",
    responses={
        403: {"description": "Forbidden", "model": ErrorModel},
        409: {"description": "Lab exists", "model": ErrorModel},
    },
    status_code=201,
    summary="Create user lab",
)
async def post_new_lab(
    username: str,
    lab: LabSpecification,
    response: Response,
    x_auth_request_token: str = Header(...),
    context: RequestContext = Depends(context_dependency),
) -> None:
    """Create a new Lab pod for a given user"""
    gafaelfawr_client = context.factory.create_gafaelfawr_client()
    try:
        user = await gafaelfawr_client.get_user_info(x_auth_request_token)
    except InvalidUserError:
        raise HTTPException(status_code=403, detail="Forbidden")
    if user.username != username:
        raise HTTPException(status_code=403, detail="Forbidden")

    context.logger.debug(f"Received creation request for {username}")
    lab_manager = context.factory.create_lab_manager()
    try:
        await lab_manager.create_lab(user, x_auth_request_token, lab)
    except LabExistsError:
        raise HTTPException(status_code=409, detail="Conflict")
    url = f"{_external_url()}/nublado/spawner/v1/labs/{username}"
    response.headers["Location"] = url


@router.delete(
    "/{username}",
    summary="Delete user lab",
    responses={
        404: {"description": "Lab not found", "model": ErrorModel},
        403: {"description": "Forbidden", "model": ErrorModel},
    },
    status_code=204,
)
async def delete_user_lab(
    username: str,
    context: RequestContext = Depends(context_dependency),
) -> None:
    """Stop a running pod."""
    lab_manager = context.factory.create_lab_manager()
    try:
        await lab_manager.delete_lab(username)
    except NoUserMapError:
        raise HTTPException(status_code=404, detail="Not found")
    return


@router.get(
    "/{username}/events",
    summary="Get Lab event stream for a user's current operation",
    responses={
        403: {"description": "Forbidden", "model": ErrorModel},
    },
    # FIXME: Not at all sure how to do response model/class for this
)
async def get_user_events(
    username: str,
    x_auth_request_user: str = Header(...),
    context: RequestContext = Depends(context_dependency),
) -> EventSourceResponse:
    """Returns the events for the lab of the given user"""
    if username != x_auth_request_user:
        raise HTTPException(status_code=403, detail="Forbidden")

    # If the user doesn't exist, publishing events for them will just hang
    # forever, so return an immediate 404. No one should watch for events
    # before creating a lab.
    if not context.user_map.get(username):
        raise HTTPException(status_code=404, detail="Not found")

    return context.event_manager.publish(username)


@router.get(
    "/spawner/v1/user-status",
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
