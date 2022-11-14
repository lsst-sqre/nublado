import asyncio
from collections.abc import AsyncGenerator
from typing import Optional

from sse_starlette.sse import ServerSentEvent
from structlog.stdlib import BoundLogger

from ..models.v1.event import EventMap, EventQueue


class EventManager:
    def __init__(self, logger: BoundLogger, events: EventMap) -> None:
        self.logger = logger
        self.events = events

    async def user_event_publisher(
        self,
        username: str,
    ) -> AsyncGenerator[ServerSentEvent, None]:
        try:
            while True:
                evs: Optional[EventQueue] = self.events.get(username)
                if evs:
                    for ev in evs:
                        if ev.sent:
                            continue
                        sse = ev.toSSE()
                        ev.sent = True
                        yield sse
                await asyncio.sleep(1.0)
        except asyncio.CancelledError as e:
            self.logger.info(f"User event stream disconnected for {username}")
            # Clean up?
            raise e
