"""Routes for lab manipulation (start, stop, get status, see events)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from safir.models import ErrorLocation, ErrorModel
from safir.slack.webhook import SlackRouteErrorHandler
from sse_starlette import EventSourceResponse

from ..dependencies.context import RequestContext, context_dependency
from ..dependencies.user import user_dependency, username_path_dependency
from ..exceptions import (
    InsufficientQuotaError,
    InvalidDockerReferenceError,
    OperationConflictError,
    PermissionDeniedError,
    UnknownDockerImageError,
    UnknownUserError,
)
from ..models.domain.gafaelfawr import GafaelfawrUser
from ..models.v1.lab import LabSpecification, UserLabState

router = APIRouter(route_class=SlackRouteErrorHandler)
"""Router to mount into the application."""

__all__ = ["router"]


@router.get(
    "/spawner/v1/labs",
    responses={403: {"description": "Forbidden", "model": ErrorModel}},
    summary="List all users with running labs",
    tags=["hub"],
)
async def get_lab_users(
    context: Annotated[RequestContext, Depends(context_dependency)],
) -> list[str]:
    return await context.lab_manager.list_lab_users(only_running=True)


@router.get(
    "/spawner/v1/labs/{username}",
    response_model=UserLabState,
    responses={
        403: {"description": "Forbidden", "model": ErrorModel},
        404: {"description": "Lab not found", "model": ErrorModel},
    },
    summary="Status of user's lab",
    tags=["hub"],
)
async def get_lab_state(
    username: str,
    context: Annotated[RequestContext, Depends(context_dependency)],
) -> UserLabState:
    state = await context.lab_manager.get_lab_state(username)
    if not state:
        msg = f"Unknown user {username}"
        raise UnknownUserError(msg, ErrorLocation.path, ["username"])
    return state


@router.post(
    "/spawner/v1/labs/{username}/create",
    responses={
        403: {"description": "Forbidden", "model": ErrorModel},
        409: {"description": "Lab exists", "model": ErrorModel},
    },
    status_code=201,
    summary="Create user lab",
    tags=["user"],
)
async def post_new_lab(
    username: str,
    lab: LabSpecification,
    context: Annotated[RequestContext, Depends(context_dependency)],
    user: Annotated[GafaelfawrUser, Depends(user_dependency)],
    response: Response,
) -> None:
    if username != user.username:
        raise PermissionDeniedError("Permission denied")

    # The user is valid and matches the route. Attempt the lab creation.
    try:
        await context.lab_manager.create_lab(user, lab)
    except InsufficientQuotaError as e:
        e.location = ErrorLocation.body
        e.field_path = ["options", "size"]
        raise
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
        409: {
            "description": "Another operation in progress",
            "model": ErrorModel,
        },
    },
    status_code=204,
    tags=["hub"],
)
async def delete_user_lab(
    username: str,
    context: Annotated[RequestContext, Depends(context_dependency)],
) -> None:
    try:
        await context.lab_manager.delete_lab(username)
    except UnknownUserError as e:
        e.location = ErrorLocation.path
        e.field_path = ["username"]
        raise
    except OperationConflictError:
        raise
    except Exception as e:
        # The exception was already reported to Slack at the service layer, so
        # convert it to a standard error message instead of letting it
        # propagate as an uncaught exception.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=[{"msg": "Failed to delete lab", "type": "delete_failed"}],
        ) from e


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
    tags=["user"],
)
async def get_lab_events(
    username: Annotated[str, Depends(username_path_dependency)],
    context: Annotated[RequestContext, Depends(context_dependency)],
) -> EventSourceResponse:
    try:
        generator = context.lab_manager.events_for_user(username)
        return EventSourceResponse(generator)
    except UnknownUserError as e:
        e.location = ErrorLocation.path
        e.field_path = ["username"]
        raise
