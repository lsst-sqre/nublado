import asyncio
from collections.abc import AsyncGenerator

from fastapi import Depends
from safir.dependencies.logger import logger_dependency
from sse_starlette.sse import EventSourceResponse, ServerSentEvent
from structlog.stdlib import BoundLogger

from ...runtime.events import user_events
from .router import external_router


@external_router.get(
    "/spawner/v1/labs/{username}/events",
    summary="Get Lab event stream for a user's current operation",
)
async def get_user_events(
    username: str,
    logger: BoundLogger = Depends(logger_dependency),
) -> EventSourceResponse:
    """Requires exec:notebook and valid user token"""

    async def user_event_publisher(
        username: str,
    ) -> AsyncGenerator[ServerSentEvent, None]:
        try:
            while True:
                evs = user_events.get(username, [])
                if evs:
                    for ev in evs:
                        if ev.sent:
                            continue
                        sse = ev.toSSE()
                        ev.sent = True
                        yield sse
                await asyncio.sleep(1.0)
        except asyncio.CancelledError as e:
            logger.info(f"User event stream disconnected for {username}")
            # Clean up?
            raise e

    return EventSourceResponse(user_event_publisher(username))
