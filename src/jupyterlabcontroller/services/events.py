import asyncio
from collections.abc import AsyncGenerator

from fastapi import Depends
from safir.dependencies.logger import logger_dependency
from sse_starlette.sse import ServerSentEvent
from structlog.stdlib import BoundLogger

from ..dependencies.events import event_dependency
from ..models.v1.external.event import EventMap


async def user_event_publisher(
    username: str,
    logger: BoundLogger = Depends(logger_dependency),
    user_events: EventMap = Depends(event_dependency),
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
