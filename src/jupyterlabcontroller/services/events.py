import asyncio
from asyncio import Queue, QueueEmpty
from collections.abc import AsyncGenerator
from typing import Dict

from sse_starlette import EventSourceResponse
from structlog.stdlib import BoundLogger

from ..models.v1.event import Event, EventTypes


class EventGenerator:
    """This is the queue of events for a single user.  It is the thing
    that will publish the ServerSentEvents used by the Hub for progress
    reporting.  cf https://github.com/sysid/sse-starlette/issues/42
    """

    def __init__(self, username: str, logger: BoundLogger) -> None:
        self.username = username
        self.logger = logger
        self.queue: Queue[Event] = Queue()

    def __aiter__(self) -> "EventGenerator":
        return self

    async def __anext__(self) -> Event:
        return await self.queue.get()

    async def asend(self, value: Event) -> None:
        await self.queue.put(value)

    async def message_generator(self) -> AsyncGenerator:
        try:
            while True:
                try:
                    ev = self.queue.get_nowait()
                except QueueEmpty:
                    # We're out of events...so poll until a new one arrives?
                    #
                    # FIXME really use a semaphore?  Don't have a good mental
                    # model here.
                    await asyncio.sleep(1.0)
                    continue
                if ev.sent:
                    continue
                sse = ev.toSSE()
                ev.sent = True
                yield sse
                if ev.event in (EventTypes.COMPLETE, EventTypes.FAILED):
                    return  # Close the stream.
        except asyncio.CancelledError as exc:
            self.logger.info(
                f"User event stream disconnected for {self.username}: {exc}"
            )
            # Clean up?


class EventManager:
    """Event mapper for jupyterlab-controller.  Maps usernames to
    event streams.  This will be initialized as a per-process global,
    although the underlying EventMap will eventually be persisted
    to Redis."""

    def __init__(self, logger: BoundLogger) -> None:
        self.logger = logger
        self._dict: Dict[str, EventGenerator] = dict()

    def get(self, key: str) -> EventGenerator:
        if key not in self._dict:
            self._dict[key] = EventGenerator(username=key, logger=self.logger)
        return self._dict[key]

    def set(self, key: str, item: EventGenerator) -> None:
        self._dict[key] = item

    def remove(self, key: str) -> None:
        try:
            del self._dict[key]
        except KeyError:
            pass

    def publish(
        self,
        username: str,
    ) -> EventSourceResponse:
        user_events = self.get(username)
        return EventSourceResponse(user_events.message_generator())
