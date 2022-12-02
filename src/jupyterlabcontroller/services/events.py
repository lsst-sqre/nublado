import asyncio
from collections.abc import AsyncGenerator
from typing import Deque

from sse_starlette.sse import ServerSentEvent
from structlog.stdlib import BoundLogger

from ..models.v1.event import Event


class EventManager:
    def __init__(
        self, username: str, logger: BoundLogger, events: Deque[Event]
    ) -> None:
        self.username = username
        self.logger = logger
        self.events = events

    @property
    async def publish(
        self,
    ) -> AsyncGenerator[ServerSentEvent, None]:
        try:
            while True:
                for ev in self.events:
                    if ev.sent:
                        continue
                    sse = ev.toSSE()
                    ev.sent = True
                    yield sse
                # FIXME really use a semaphore
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            self.logger.info(
                f"User event stream disconnected for {self.username}"
            )
            # Clean up?
            # raise  # probably not actually an error
