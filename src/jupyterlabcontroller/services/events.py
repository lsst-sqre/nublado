import asyncio
from collections.abc import AsyncGenerator

from sse_starlette.sse import ServerSentEvent
from structlog.stdlib import BoundLogger

from ..models.domain.eventmap import EventMap


class EventManager:
    def __init__(self, logger: BoundLogger, event_map: EventMap) -> None:
        self.logger = logger
        self.event_map = event_map

    async def publish(
        self,
        username: str,
    ) -> AsyncGenerator[ServerSentEvent, None]:
        events = self.event_map.get(username)
        try:
            while True:
                for ev in events:
                    if ev.sent:
                        continue
                    sse = ev.toSSE()
                    ev.sent = True
                    yield sse
                # FIXME really use a semaphore
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            self.logger.info(f"User event stream disconnected for {username}")
            # Clean up?
            # raise  # probably not actually an error
