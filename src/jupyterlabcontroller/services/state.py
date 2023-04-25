"""Maintain and answer questions about user lab state and events."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Optional

from aiojobs import Scheduler
from safir.datetime import current_datetime
from safir.slack.blockkit import SlackException
from safir.slack.webhook import SlackWebhookClient
from sse_starlette import ServerSentEvent
from structlog.stdlib import BoundLogger

from ..constants import LAB_STATE_REFRESH_INTERVAL
from ..exceptions import LabExistsError, UnknownUserError
from ..models.domain.lab import UserLab
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

        # Mapping of usernames to internal lab state.
        self._labs: dict[str, UserLab] = {}

        # Triggered when any background thread monitoring spawn progress
        # completes. This has to be triggered manually, so there must be a
        # top-level exception handler for each spawner task that ensures it is
        # set when the spawner task exits for any reason. Otherwise, the
        # reaper task may never realize a spawner has finished and wake up.
        self._spawner_done = asyncio.Event()

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
        if username not in self._labs:
            raise UnknownUserError(f"Unknown user {username}")

        # Get the event list and add our trigger to it. We grab a separate
        # reference to the event list, rather than using self._labs inside the
        # iterator, so that if the event list is cleared (via replacement with
        # an empty list) while we are listening, we will only see the old
        # list.
        events = self._labs[username].events
        trigger = asyncio.Event()
        if events:
            trigger.set()
        self._labs[username].triggers.append(trigger)

        # The iterator waits for the trigger and returns any new events,
        # calling _remove_trigger after it sees an event that indicates the
        # operation has completed.
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

    async def get_lab_state(self, username: str) -> UserLabState:
        """Get lab state for a user.

        Parameters
        ----------
        username
            Username to retrieve lab state for.

        Returns
        -------
        UserLabState
            Lab state for that user.

        Raises
        ------
        UnknownUserError
            Raised if the given user has no lab.
        """
        if username in self._labs:
            return self._labs[username].state
        else:
            raise UnknownUserError(f"Unknown user {username}")

    async def list_lab_users(self, only_running: bool = False) -> list[str]:
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
                if s.state.status == LabStatus.RUNNING
            ]
        else:
            return list(self._labs.keys())

    async def publish_deletion(self, username: str, message: str) -> None:
        """Publish a lab deletion completion event for a user.

        Notifies any current listeners to the event stream that the operation
        is complete before deleting the recorded user state entirely.

        Parameters
        ----------
        username
            User whose lab the event is for.
        message
            Event message.
        """
        event = Event(message=message, type=EventType.COMPLETE)
        await self._add_event(username, event)
        lab = self._labs[username]
        del self._labs[username]
        await self._clear_events(lab)

    async def publish_error(
        self, username: str, message: str, fatal: bool = False
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
            self._logger.error("Lab creation failed", user=username)
            self._labs[username].state.status = LabStatus.FAILED
            self._labs[username].state.internal_url = None

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
        self._logger.debug(msg, user=username, progress=progress)

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
        self._labs[username].state.pod = PodState.PRESENT
        self._labs[username].state.status = LabStatus.PENDING

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
        lab = self._labs[username]
        await self._clear_events(lab)
        lab.state.status = LabStatus.TERMINATING
        lab.state.internal_url = None
        await self.publish_event(username, message, progress)

    async def start(self) -> None:
        """Synchronize with Kubernetes and start a background refresh task.

        Examine Kubernetes for current user lab state, update our internal
        data structures accordingly, and then start a background refresh task
        that does this periodically. (Labs may be destroyed by Kubernetes node
        upgrades, for example.)
        """
        if self._scheduler:
            msg = "User lab state tasks already running, cannot start again"
            self._logger.warning(msg)
            return
        await self._reconcile_lab_state()
        self._logger.info("Starting user lab state reconciliation")
        self._scheduler = Scheduler()
        await self._scheduler.spawn(self._refresh_loop())
        self._logger.info("Starting reaper for spawn monitoring tasks")
        await self._scheduler.spawn(self._reap_spawners())

    async def start_spawn(
        self,
        username: str,
        state: UserLabState,
        spawner: Callable[[], Awaitable[str]],
    ) -> None:
        """Start lab creation for a user in a background thread.

        Parameters
        ----------
        username
            Username of user.
        state
            Initial user lab state.
        spawner
            Asynchronous callback that will create the Kubernetes objects for
            the lab and return the URL on which it will listen after it
            starts.

        Raises
        ------
        LabExistsError
            Raised if this user already has a lab (in any state).
        """
        if username in self._labs:
            msg = "Lab already exists"
            await self.publish_error(username, msg, fatal=True)
            raise LabExistsError(f"Lab already exists for {username}")
        self._labs[username] = UserLab(state=state)
        task = asyncio.create_task(self._spawn(username, spawner))
        self._labs[username].spawner = task

    async def stop(self) -> None:
        """Stop the background refresh task."""
        if not self._scheduler:
            msg = "User lab state background tasks were already stopped"
            self._logger.warning(msg)
            return
        self._logger.info("Stopping user lab state background tasks")
        await self._scheduler.close()
        self._scheduler = None
        self._logger.info("Stopping spawning monitor tasks")
        for state in self._labs.values():
            if state.spawner:
                spawner = state.spawner
                state.spawner = None
                spawner.cancel("Shutting down")
                try:
                    await spawner
                except asyncio.CancelledError:
                    pass

    async def _add_event(self, username: str, event: Event) -> None:
        """Publish an event for the given user.

        Parameters
        ----------
        username
            Username the event is for.
        event
            Event to publish.
        """
        self._labs[username].events.append(event)
        for trigger in self._labs[username].triggers:
            trigger.set()

    async def _clear_events(self, lab: UserLab) -> None:
        """Safely clear the event list for a user.

        If the record for the user is about to be deleted, remove it from
        ``self._labs`` before calling this method to ensure that nothing
        starts adding new events and triggers while the deletion is in
        progress.

        Parameters
        ----------
        lab
            User lab data holding the event stream to clear.
        """
        events = lab.events
        triggers = lab.triggers
        lab.events = []
        lab.triggers = []

        # If the final event in the list of events is not a completion
        # event, add a synthetic completion event. Then notify any listeners.
        # This ensures all the listeners will complete.
        if not events or not events[-1].done:
            event = Event(message="Operation aborted", type=EventType.FAILED)
            events.append(event)
        for trigger in triggers:
            trigger.set()

    async def _reap_spawners(self) -> None:
        """Wait for spawner tasks to complete and record their status.

        When a user spawns a lab, the lab controller creates a background task
        to create the Kubernetes objects and then wait for the pod to finish
        starting. Something needs to await those tasks so that they can be
        cleanly finalized and to catch any uncaught exceptions. That function
        is performed by a background task running this method.

        Notes
        -----
        There unfortunately doesn't appear to be an API to wait for a group of
        awaitables or tasks but return as soon as the first one succeeds or
        fails, instead of waiting for all of them. We therefore need to do the
        locking and coordination ourselves by having the spawner thread notify
        the ``_spawner_done`` `asyncio.Event`.
        """
        while True:
            await self._spawner_done.wait()
            self._spawner_done.clear()
            for username, state in self._labs.items():
                if state.spawner and state.spawner.done():
                    spawner = state.spawner
                    state.spawner = None
                    try:
                        await spawner
                    except Exception as e:
                        msg = "Uncaught exception in spawner thread"
                        self._logger.exception(msg, user=username)
                        if self._slack:
                            await self._slack.post_uncaught_exception(e)
                        state.state.status = LabStatus.FAILED

    async def _reconcile_lab_state(self) -> None:
        """Reconcile user lab state with Kubernetes.

        This method is called on startup and then periodically from a
        background thread to check Kubernetes and ensure the in-memory record
        of the user's lab state matches reality. On startup, it also needs to
        recreate the internal state from the contents of Kubernetes.
        """
        self._logger.info("Reconciling user lab state with Kubernetes")
        known_users = set(self._labs.keys())
        observed = await self._kubernetes.get_observed_user_state(
            self._namespace_prefix
        )

        # If the set of users we expected to see changed during
        # reconciliation, we may be running into all sorts of race
        # conditions. Just skip this background update; we'll catch any
        # inconsistencies the next time around.
        if set(self._labs.keys()) != known_users:
            msg = "Known users changed during reconciliation, skipping"
            self._logger.info(msg)
            return

        # First pass: check all users already recorded in internal state
        # against Kubernetes and correct them (or remove them) if needed.
        for username, lab in list(self._labs.items()):
            if lab.spawner is not None:
                continue
            if lab.state.status == LabStatus.FAILED:
                continue
            if username not in observed:
                msg = f"Expected user {username} not found in Kubernetes"
                self._logger.warning(msg)
                await self.publish_deletion(username, "Lab pod disappeared")
            else:
                observed_state = observed[username]
                if observed_state.status != lab.state.status:
                    self._logger.warning(
                        f"Expected status for {username} is"
                        f" {lab.state.status}, but observed status is"
                        f" {observed_state.status}"
                    )
                    lab.state.status = observed_state.status

        # Second pass: take observed state and create any missing internal
        # state. This is the normal case after a restart of the lab
        # controller.
        for username in set(observed.keys()) - known_users:
            if username not in self._labs:
                msg = f"Creating record for user {username} from Kubernetes"
                self._logger.info(msg)
                self._labs[username] = UserLab(state=observed[username])

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
        if username not in self._labs:
            return
        self._labs[username].triggers = [
            t for t in self._labs[username].triggers if t != trigger
        ]

    async def _spawn(
        self, username: str, spawner: Callable[[], Awaitable[str]]
    ) -> None:
        """Spawn a lab and wait for it to start running.

        This is run as a background task to create a user's lab and wait for
        it to start running, notifing an `asyncio.Event` variable when it
        completes for any reason.

        Parameters
        ----------
        username
            Username of user whose lab is being spawned.
        spawner
            Asynchronous callable that does the work of creating the
            Kubernetes objects for the lab.
        """
        namespace = f"{self._namespace_prefix}-{username}"
        pod_name = f"nb-{username}"
        try:
            await self._clear_events(self._labs[username])
            msg = f"Starting lab creation for {username}"
            await self.publish_event(username, msg, 1)
            internal_url = await spawner()
            await self._kubernetes.wait_for_pod_creation(pod_name, namespace)
        except Exception as e:
            self._logger.exception("Lab creation failed")
            if self._slack:
                if isinstance(e, SlackException):
                    e.user = username
                    await self._slack.post_exception(e)
                else:
                    await self._slack.post_uncaught_exception(e)
            await self.publish_error(username, str(e), fatal=True)
        else:
            msg = f"Lab Kubernetes pod started for {username}"
            event = Event(message=msg, type=EventType.COMPLETE)
            await self._add_event(username, event)
            self._labs[username].state.status = LabStatus.RUNNING
            self._labs[username].state.internal_url = internal_url
            self._logger.info("Lab created")
        finally:
            self._spawner_done.set()
