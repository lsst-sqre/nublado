"""User-facing routes, as defined in sqr-066 (https://sqr-066.lsst.io),
specifically for watching user events"""
from fastapi import APIRouter, Depends
from safir.models import ErrorModel
from sse_starlette import EventSourceResponse

from ..dependencies.context import context_dependency
from ..dependencies.token import user_token_dependency
from ..factory import Context

# FastAPI routers
router = APIRouter()
#
# Event stream handler
#


@router.get(
    "/spawner/v1/labs/{username}/events",
    summary="Get Lab event stream for a user's current operation",
    responses={
        403: {"description": "Forbidden", "model": ErrorModel},
    },
    # FIXME: Not at all sure how to do response model/class for this
)
async def get_user_events(
    username: str,
    context: Context = Depends(context_dependency),
    user_token: str = Depends(user_token_dependency),
) -> EventSourceResponse:
    """Returns the events for the lab of the given user"""
    event_manager = context.event_manager
    # should return EventSourceResponse:
    return event_manager.publish(username)
