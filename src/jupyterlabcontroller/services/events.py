"""Record and return spawner events."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from sse_starlette import ServerSentEvent

from ..exceptions import UnknownUserError
from ..models.v1.event import Event, EventType


class EventManager:
    """Manage lab spawn event queues for users.

    This is managed as a per-process global. Eventually, it will use Redis
    queues instead.
    """

    def __init__(self) -> None:
        # Mapping of usernames to spawn events for that user.
        self._events: dict[str, list[Event]] = {}

        # Triggers per user that we use to notify any listeners of new events.
        self._triggers: dict[str, list[asyncio.Event]] = {}

    def events_for_user(self, username: str) -> AsyncIterator[ServerSentEvent]:
        """Iterator over the events for a user.

        Each iterator gets its own `asyncio.Event` to notify it when more
        events have been added.

        Parameters
        ----------
        username
            Username for which to retrieve events.

        Yields
        ------
        Event
            Events for that user until a completion or failure event is seen.
        """
        if username not in self._events:
            raise UnknownUserError(f"Unknown user {username}")

        events = self._events[username]
        trigger = asyncio.Event()
        if events:
            trigger.set()
        self._triggers[username].append(trigger)

        async def iterator() -> AsyncIterator[ServerSentEvent]:
            position = 0
            try:
                while True:
                    trigger.clear()
                    event_len = len(events)
                    for event in events[position:event_len]:
                        yield event.to_sse()
                        if event.done:
                            return
                    position = event_len
                    await trigger.wait()
            finally:
                self._remove_trigger(username, trigger)

        return iterator()

    def publish_event(self, username: str, event: Event) -> None:
        """Publish an event for the given user.

        Parameters
        ----------
        username
            Username the event is for.
        event
            Event to publish.
        """
        if username in self._events:
            self._events[username].append(event)
            for trigger in self._triggers[username]:
                trigger.set()
        else:
            self._events[username] = [event]
            self._triggers[username] = []

    def reset_user(self, username: str) -> None:
        """Reset the event queue for a user.

        Called when we delete the user's lab or otherwise reset the user's
        state such that old events are no longer of interest.

        Parameters
        ----------
        username
            Username to reset.
        """
        if username not in self._events:
            return

        # Detach the list of events from our data so that no more can be
        # added. If the final event in the list of events is not a completion
        # event, add a synthetic completion event. Then notify any listeners.
        # This ensures all the listeners will complete.
        events = self._events[username]
        del self._events[username]
        if not events or not events[-1].done:
            event = Event(message="Operation aborted", type=EventType.FAILED)
            events.append(event)
        triggers = self._triggers[username]
        del self._triggers[username]
        for trigger in triggers:
            trigger.set()

    def _remove_trigger(self, username: str, trigger: asyncio.Event) -> None:
        """Called when a generator is complete.

        Does some housekeeping by removing the `asyncio.Event` for that
        generator. Strictly speaking, this probably isn't necessary; we will
        release all of the events when the user is reset, and there shouldn't
        be enough requests for the user's events before that happens for the
        memory leak to matter. But do this the right way anyway.

        Parameters
        ----------
        username
            User whose generator has completed.
        trigger
            Corresponding trigger to remove.
        """
        if username not in self._triggers:
            return
        self._triggers[username] = [
            t for t in self._triggers[username] if t != trigger
        ]
