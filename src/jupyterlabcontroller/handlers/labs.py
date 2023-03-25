"""Routes for lab manipulation (start, stop, get status, see events)."""

from typing import List

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from safir.models import ErrorModel
from sse_starlette import EventSourceResponse

from ..dependencies.context import RequestContext, context_dependency
from ..exceptions import InvalidUserError, LabExistsError, NoUserMapError
from ..models.v1.lab import LabSpecification, UserData

router = APIRouter()
"""Router to mount into the application."""

__all__ = ["router"]


@router.get(
    "/spawner/v1/labs",
    responses={403: {"description": "Forbidden", "model": ErrorModel}},
    summary="List all users with running labs",
)
async def get_lab_users(
    context: RequestContext = Depends(context_dependency),
) -> List[str]:
    """Returns a list of all users with running labs."""
    return await context.user_map.running()


@router.get(
    "/spawner/v1/labs/{username}",
    response_model=UserData,
    responses={
        403: {"description": "Forbidden", "model": ErrorModel},
        404: {"description": "Lab not found", "model": ErrorModel},
    },
    summary="Status of user's lab",
)
async def get_userdata(
    username: str,
    context: RequestContext = Depends(context_dependency),
) -> UserData:
    userdata = context.user_map.get(username)
    if userdata is None:
        raise HTTPException(status_code=404, detail="Not found")
    return userdata


@router.post(
    "/spawner/v1/labs/{username}/create",
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
    url = context.request.url_for("get_userdata", username=username)
    response.headers["Location"] = str(url)


@router.delete(
    "/spawner/v1/labs/{username}",
    summary="Delete user lab",
    responses={
        403: {"description": "Forbidden", "model": ErrorModel},
        404: {"description": "Lab not found", "model": ErrorModel},
    },
    status_code=204,
)
async def delete_user_lab(
    username: str,
    context: RequestContext = Depends(context_dependency),
) -> None:
    lab_manager = context.factory.create_lab_manager()
    try:
        await lab_manager.delete_lab(username)
    except NoUserMapError:
        raise HTTPException(status_code=404, detail="Not found")
    return


@router.get(
    "/spawner/v1/labs/{username}/events",
    summary="Get event stream for user's lab",
    description=(
        "Returns a stream of server-sent events representing progress in"
        " creating the user's lab. The stream ends when the lab creation"
        " succeeds or fails."
    ),
    responses={
        403: {"description": "Forbidden", "model": ErrorModel},
        404: {"description": "Lab not found", "model": ErrorModel},
    },
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
