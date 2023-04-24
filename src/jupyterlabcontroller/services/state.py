"""Maintain and answer questions about user lab state and events."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Optional

from aiojobs import Scheduler
from safir.datetime import current_datetime
from safir.slack.webhook import SlackWebhookClient
from sse_starlette import ServerSentEvent
from structlog.stdlib import BoundLogger

from ..constants import LAB_STATE_REFRESH_INTERVAL
from ..exceptions import UnknownUserError
from ..models.v1.event import Event, EventType
from ..models.v1.lab import LabStatus, PodState, UserLabState
from ..storage.k8s import K8sStorageClient

__all__ = ["LabStateManager"]


class LabStateManager:
    """Manage the record of user lab state.

    This is currently managed as a per-process global. Eventually, it will use
    Redis queues instead.

    Parameters
    ----------
    kubernetes
        Kubernetes storage.
    namespace_prefix
        Prefix of the namespaces used for user lab environments.
    logger
        Logger to use.

    Notes
    -----
    Many methods that currently do not need to be async are marked async
    anyway since they will need to be async when the backing store is Redis
    and this will minimize future disruption.
    """

    def __init__(
        self,
        *,
        namespace_prefix: str,
        kubernetes: K8sStorageClient,
        slack_client: SlackWebhookClient | None,
        logger: BoundLogger,
    ) -> None:
        self._namespace_prefix = namespace_prefix
        self._kubernetes = kubernetes
        self._slack = slack_client
        self._logger = logger

        # Background task management.
        self._scheduler: Optional[Scheduler] = None

        # Mapping of usernames to last known lab state.
        self._labs: dict[str, UserLabState] = {}

        # Mapping of usernames to spawn events for that user.
        self._events: dict[str, list[Event]] = {}

        # Triggers per user that we use to notify any listeners of new events.
        self._triggers: dict[str, list[asyncio.Event]] = {}

    async def create_user(self, username: str, state: UserLabState) -> None:
        """Create (or replace) a lab state entry for a user.

        Parameters
        ----------
        username
            Username of user.
        state
            Initial user lab state.
        """
        self._labs[username] = state
        await self.reset_user_events(username)

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

        Raises
        ------
        UnknownUserError
            Raised if there is no event stream for this user.
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

    async def is_lab_present(self, username: str) -> bool:
        """Whether the given user has a running lab.

        Parameters
        ----------
        username
            Username to check.

        Returns
        -------
        bool
            `True` if the user has a lab in any state (including failure),
            `False` otherwise.
        """
        return username in self._labs

    async def get_user(self, username: str) -> UserLabState | None:
        """Get lab state for a user.

        Parameters
        ----------
        username
            Username to retrieve state for.

        Returns
        -------
        UserLabState or None
            Lab state for that user, or `None` if that user is not known.
        """
        return self._labs.get(username)

    async def list_users(self, only_running: bool = False) -> list[str]:
        """List all users with labs.

        Parameters
        ----------
        only_running
            If set to `True`, only list users with running labs, not labs in
            other states.

        Returns
        -------
        list of str
            Users with labs.
        """
        if only_running:
            return [
                u
                for u, s in self._labs.items()
                if s.status == LabStatus.RUNNING
            ]
        else:
            return list(self._labs.keys())

    async def publish_completion(
        self, username: str, message: str, internal_url: str
    ) -> None:
        """Publish a lab spawn completion event for a user.

        Parameters
        ----------
        username
            User whose lab the event is for.
        message
            Event message.
        internal_url
            Internal URL of the newly-spawned lab.
        """
        event = Event(message=message, type=EventType.COMPLETE)
        await self._add_event(username, event)
        if username in self._labs:
            self._labs[username].status = LabStatus.RUNNING
            self._labs[username].internal_url = internal_url

    async def publish_deletion(self, username: str, message: str) -> None:
        """Publish a lab deletion completion event for a user.

        Parameters
        ----------
        username
            User whose lab the event is for.
        message
            Event message.
        """
        event = Event(message=message, type=EventType.COMPLETE)
        await self._add_event(username, event)
        if username in self._labs:
            del self._labs[username]

    async def publish_error(
        self, username: str, message: str, fatal: bool = True
    ) -> None:
        """Publish a lab spawn or deletion failure event for a user.

        Parameters
        ----------
        username
            User whose lab the event is for.
        message
            Event message.
        fatal
            Whether the event is fatal (the operation has been aborted).
        """
        event = Event(message=message, type=EventType.ERROR)
        await self._add_event(username, event)
        self._logger.error(f"Spawning error: {message}")
        if fatal:
            event = Event(message="Lab creation failed", type=EventType.FAILED)
            await self._add_event(username, event)
            self._logger.error("Lab creation failed")
            if username in self._labs:
                self._labs[username].status = LabStatus.FAILED
                self._labs[username].internal_url = None

    async def publish_event(
        self, username: str, message: str, progress: int
    ) -> None:
        """Publish a lab spawn or deletion informational event for a user.

        Parameters
        ----------
        username
            User whose lab the event is for.
        message
            Event message.
        progress
            New progress percentage.
        """
        event = Event(message=message, progress=progress, type=EventType.INFO)
        await self._add_event(username, event)
        msg = f"Spawning event: {message}"
        self._logger.debug(msg, username=username, progress=progress)

    async def publish_pod_creation(
        self, username: str, message: str, progress: int
    ) -> None:
        """Publish the creation of a lab pod.

        This also updates the user lab state accordingly.

        Parameters
        ----------
        username
            User whose lab the event is for.
        message
            Event message.
        progress
            New progress percentage.
        """
        await self.publish_event(username, message, progress)
        if username in self._labs:
            self._labs[username].pod = PodState.PRESENT
            self._labs[username].status = LabStatus.PENDING

    async def publish_start_deletion(
        self, username: str, message: str, progress: int
    ) -> None:
        """Publish the beginning of deleting a lab environment.

        This also updates the user lab state accordingly.

        Parameters
        ----------
        username
            User whose lab the event is for.
        message
            Event message.
        progress
            New progress percentage.

        Raises
        ------
        UnknownUserError
            Raised if no lab currently exists for this user.
        """
        if username not in self._labs:
            raise UnknownUserError(f"Unknown user {username}")
        self._labs[username].status = LabStatus.TERMINATING
        self._labs[username].internal_url = None
        await self.publish_event(username, message, progress)

    async def reset_user_events(self, username: str) -> None:
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

    async def start(self) -> None:
        """Synchronize with Kubernetes and start a background refresh task.

        Examine Kubernetes for current user lab state, update our internal
        data structures accordingly, and then start a background refresh task
        that does this periodically. (Labs may be destroyed by Kubernetes node
        upgrades, for example.)
        """
        if self._scheduler:
            msg = "User lab state reconciliation already running, cannot start"
            self._logger.warning(msg)
            return
        await self._reconcile_lab_state()
        self._logger.info("Starting user lab state reconciliation")
        self._scheduler = Scheduler()
        await self._scheduler.spawn(self._refresh_loop())

    async def stop(self) -> None:
        """Stop the background refresh task."""
        if not self._scheduler:
            msg = "User lab state reconciliation was already stopped"
            self._logger.warning(msg)
            return
        self._logger.info("Stopping user lab state reconciliation")
        await self._scheduler.close()
        self._scheduler = None

    async def _add_event(self, username: str, event: Event) -> None:
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

    async def _reconcile_lab_state(self) -> None:
        """Reconcile user lab state with Kubernetes.

        This method is called on startup and then periodically from a
        background thread to check Kubernetes and ensure the in-memory record
        of the user's lab state matches reality. On startup, it also needs to
        recreate the internal state from the contents of Kubernetes.
        """
        self._logger.info("Reconciling user lab state with Kubernetes")
        observed = await self._kubernetes.get_observed_user_state(
            self._namespace_prefix
        )
        known_users = set(self._labs.keys())

        # First pass: check all users already recorded in internal state
        # against Kubernetes and correct them (or remove them) if needed.
        for username in known_users:
            state = self._labs[username]
            if state.status == LabStatus.FAILED:
                continue
            if username not in observed:
                msg = f"Expected user {username} not found in Kubernetes"
                self._logger.warning(msg)
                await self.reset_user_events(username)
                del self._labs[username]
            else:
                observed_state = observed[username]
                if observed_state.status != state.status:
                    self._logger.warning(
                        f"Expected status for {username} is {state.status},"
                        f" but observed status is {observed_state.status}"
                    )
                    state.status = observed_state.status

        # Second pass: take observed state and create any missing internal
        # state. This is the normal case after a restart of the lab
        # controller.
        for username in observed.keys():
            if username not in self._labs:
                msg = f"Creating record for user {username} from Kubernetes"
                self._logger.info(msg)
                self._labs[username] = observed[username]

    async def _refresh_loop(self) -> None:
        """Run in the background by `start`, stopped with `stop`."""
        while True:
            start = current_datetime()
            try:
                await self._reconcile_lab_state()
            except Exception as e:
                self._logger.exception("Unable to reconcile user lab state")
                if self._slack:
                    await self._slack.post_uncaught_exception(e)
            delay = LAB_STATE_REFRESH_INTERVAL - (current_datetime() - start)
            if delay.total_seconds() < 1:
                msg = "User lab state reconciliation is running continuously"
                self._logger.warning(msg)
            else:
                await asyncio.sleep(delay.total_seconds())

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
