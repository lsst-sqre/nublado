"""Routes for lab manipulation (start, stop, get status, see events)."""

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from safir.models import ErrorLocation, ErrorModel
from safir.slack.webhook import SlackRouteErrorHandler
from sse_starlette import EventSourceResponse

from ..dependencies.context import RequestContext, context_dependency
from ..dependencies.user import user_dependency
from ..exceptions import (
    InvalidDockerReferenceError,
    PermissionDeniedError,
    UnknownDockerImageError,
    UnknownUserError,
)
from ..models.v1.lab import LabSpecification, UserInfo, UserLabState

router = APIRouter(route_class=SlackRouteErrorHandler)
"""Router to mount into the application."""

__all__ = ["router"]


@router.get(
    "/spawner/v1/labs",
    responses={403: {"description": "Forbidden", "model": ErrorModel}},
    summary="List all users with running labs",
)
async def get_lab_users(
    context: RequestContext = Depends(context_dependency),
) -> list[str]:
    """Returns a list of all users with running labs."""
    return await context.lab_state.list_lab_users(only_running=True)


@router.get(
    "/spawner/v1/labs/{username}",
    response_model=UserLabState,
    responses={
        403: {"description": "Forbidden", "model": ErrorModel},
        404: {"description": "Lab not found", "model": ErrorModel},
    },
    summary="Status of user's lab",
)
async def get_lab_state(
    username: str,
    context: RequestContext = Depends(context_dependency),
) -> UserLabState:
    try:
        return await context.lab_state.get_lab_state(username)
    except UnknownUserError as e:
        e.location = ErrorLocation.path
        e.field_path = ["username"]
        raise


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
    x_auth_request_token: str = Header(..., include_in_schema=False),
    context: RequestContext = Depends(context_dependency),
    user: UserInfo = Depends(user_dependency),
) -> None:
    context.rebind_logger(user=username)
    if username != user.username:
        raise PermissionDeniedError("Permission denied")
    # The user is valid and matches the route. Attempt the lab creation.
    lab_manager = context.factory.create_lab_manager()
    try:
        # FIXME User now includes x_auth_request_token
        await lab_manager.create_lab(user, x_auth_request_token, lab)
    except (InvalidDockerReferenceError, UnknownDockerImageError) as e:
        e.location = ErrorLocation.body
        e.field_path = ["options", lab.options.image_attribute]
        raise
    url = context.request.url_for("get_lab_state", username=username)
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
    context.rebind_logger(user=username)
    lab_manager = context.factory.create_lab_manager()
    try:
        await lab_manager.delete_lab(username)
    except UnknownUserError as e:
        e.location = ErrorLocation.path
        e.field_path = ["username"]
        raise
    except Exception:
        # The exception was already reported to Slack at the service layer, so
        # convert it to a standard error message instead of letting it
        # propagate as an uncaught exception.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=[{"msg": "Failed to delete lab", "type": "delete_failed"}],
        )


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
async def get_lab_events(
    username: str,
    x_auth_request_user: str = Header(..., include_in_schema=False),
    context: RequestContext = Depends(context_dependency),
) -> EventSourceResponse:
    """Returns the events for the lab of the given user"""
    if username != x_auth_request_user:
        raise PermissionDeniedError("Permission denied")
    context.rebind_logger(user=username)
    try:
        generator = context.lab_state.events_for_user(username)
        return EventSourceResponse(generator)
    except UnknownUserError as e:
        e.location = ErrorLocation.path
        e.field_path = ["username"]
        raise
