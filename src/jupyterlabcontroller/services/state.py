"""Maintain and answer questions about user lab state and events."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from typing import Optional

from aiojobs import Scheduler
from kubernetes_asyncio.client import V1Pod, V1ResourceQuota
from safir.datetime import current_datetime
from safir.slack.blockkit import SlackException
from safir.slack.webhook import SlackWebhookClient
from sse_starlette import ServerSentEvent
from structlog.stdlib import BoundLogger

from ..config import LabConfig
from ..constants import LAB_STATE_REFRESH_INTERVAL
from ..exceptions import KubernetesError, LabExistsError, UnknownUserError
from ..models.domain.kubernetes import KubernetesPodPhase
from ..models.domain.lab import UserLab
from ..models.v1.event import Event, EventType
from ..models.v1.lab import (
    LabResources,
    LabStatus,
    PodState,
    ResourceQuantity,
    UserGroup,
    UserInfo,
    UserLabState,
    UserOptions,
)
from ..storage.k8s import K8sStorageClient
from .builder import LabBuilder
from .size import SizeManager

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
        config: LabConfig,
        kubernetes: K8sStorageClient,
        size_manager: SizeManager,
        lab_builder: LabBuilder,
        slack_client: SlackWebhookClient | None,
        logger: BoundLogger,
    ) -> None:
        self._config = config
        self._kubernetes = kubernetes
        self._size_manager = size_manager
        self._builder = lab_builder
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
        if username not in self._labs:
            raise UnknownUserError(f"Unknown user {username}")
        lab = self._labs[username]

        # Ask Kubernetes for the current state so that we catch pods that have
        # been evicted or shut down behind our back by the Kubernetes cluster.
        pod = f"{username}-nb"
        namespace = self._builder.namespace_for_user(username)
        try:
            phase = await self._kubernetes.get_pod_phase(pod, namespace)
        except KubernetesError as e:
            self._logger.exception(
                "Cannot get pod status",
                user=username,
                name=pod,
                namespace=namespace,
                kind="Pod",
            )
            if self._slack:
                e.user = username
                await self._slack.post_exception(e)

            # Two options here: pessimistically assume the lab is in a failed
            # state, or optimistically assume that our current in-memory data
            # is correct. Given that we refresh state in the background
            # continuously, go with optimism; we'll update with pessimism if
            # we can ever reach Kubernetes, and telling JupyterHub to go ahead
            # and try to send the user to the lab seems like the right move.
            return lab.state

        # If the pod is missing, set the state to failed. Also set the state
        # to failed if we thought the pod was running but it's in some other
        # state. Otherwise, go with our current state.
        if phase is None:
            lab.state.status = LabStatus.FAILED
            lab.state.pod = PodState.MISSING
        elif lab.state.status == LabStatus.RUNNING:
            if phase != KubernetesPodPhase.RUNNING:
                lab.state.status = LabStatus.FAILED
        return lab.state

    async def get_lab_status(self, username: str) -> LabStatus | None:
        """Get lab status for a user.

        Parameters
        ----------
        username
            Username to retrieve lab status for.

        Returns
        -------
        LabStatus or None
            Status of lab for that user, or `None` if that user doesn't have a
            lab.
        """
        try:
            state = await self.get_lab_state(username)
            return state.status
        except UnknownUserError:
            return None

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

    async def start_lab(
        self,
        *,
        username: str,
        state: UserLabState,
        spawner: Callable[[], Awaitable[str]],
        start_progress: int,
        end_progress: int,
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
        start_progress
            Progress percentage to start at when watching pod startup events.
        end_progress
            Progress percentage to stop at when the spawn is complete.

        Raises
        ------
        LabExistsError
            Raised if this user already has a lab with a status other than
            failed. If the current status is failed, assume the spawner will
            recreate it.
        """
        if username in self._labs:
            lab = self._labs[username]
            if lab.state.status != LabStatus.FAILED:
                msg = f"Lab for {username} already exists"
                completion_event = Event(message=msg, type=EventType.COMPLETE)
                await self._add_event(username, completion_event)
                raise LabExistsError(f"Lab already exists for {username}")
        self._labs[username] = UserLab(state=state)
        await self._clear_events(self._labs[username])
        msg = f"Starting lab creation for {username}"
        await self.publish_event(username, msg, 1)
        self._labs[username].task = asyncio.create_task(
            self._monitor_spawn(
                username=username,
                spawner=spawner,
                start_progress=start_progress,
                end_progress=end_progress,
            )
        )

    async def stop_lab(
        self, username: str, deleter: Callable[[], Coroutine[None, None, None]]
    ) -> None:
        """Stop the lab for a user.

        Unlike spawning, this is done in the foreground since JupyterHub also
        expects lab shutdown to happen in the foreground. However, we use the
        same task structure since we use the presence of a running task to
        indicate that we're in the middle of an operation on that user's lab.

        Parameters
        ----------
        username
            Username of user.
        deleter
            Callback that does the work of deleting the lab.

        Raises
        ------
        KubernetesError
            Raised if a Kubernetes error prevented lab deletion.
        UnknownUserError
            Raised if no lab currently exists for this user.
        """
        if username not in self._labs:
            raise UnknownUserError(f"Unknown user {username}")
        logger = self._logger.bind(user=username)
        lab = self._labs[username]
        timeout = self._config.spawn_timeout.total_seconds()
        await self._clear_events(lab)
        lab.state.status = LabStatus.TERMINATING
        lab.state.internal_url = None
        start = current_datetime()
        lab.task = asyncio.create_task(deleter())
        try:
            async with asyncio.timeout(timeout):
                await lab.task
        except TimeoutError:
            delay = int((current_datetime() - start).total_seconds())
            msg = f"Lab deletion timed out after {delay}s"
            logger.error(msg)
            event = Event(message=msg, type=EventType.FAILED)
            await self._add_event(username, event)
            self._labs[username].state.status = LabStatus.FAILED
            self._labs[username].state.internal_url = None
        except Exception as e:
            logger.exception("Lab deletion failed")
            if self._slack:
                if isinstance(e, SlackException):
                    e.user = username
                    await self._slack.post_exception(e)
                else:
                    await self._slack.post_uncaught_exception(e)
            event = Event(message=str(e), type=EventType.ERROR)
            await self._add_event(username, event)
            event = Event(message="Lab deletion failed", type=EventType.FAILED)
            await self._add_event(username, event)
            self._labs[username].state.status = LabStatus.FAILED
            self._labs[username].state.internal_url = None
            raise
        else:
            msg = f"Lab for {username} deleted"
            completion_event = Event(message=msg, type=EventType.COMPLETE)
            await self._add_event(username, completion_event)
            await self._clear_events(lab)
            del self._labs[username]
            logger.info(msg)

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
        self._logger.info("Starting periodic reconciliation task")
        self._scheduler = Scheduler()
        await self._scheduler.spawn(self._refresh_loop())
        self._logger.info("Starting reaper for spawn monitoring tasks")
        await self._scheduler.spawn(self._reap_spawners())

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
            if state.task:
                spawner = state.task
                state.task = None
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

    async def _reflect_events(
        self,
        *,
        username: str,
        pod: str,
        namespace: str,
        start_progress: int,
        end_progress: int,
    ) -> None:
        """Monitor Kubernetes events for a pod.

        Translate these into our internal event structure and add them to the
        event list for this user. Intented to be run as a task and cancelled
        once the pod spawn completes or times out.

        Parameters
        ----------
        username
            Username for which we're spawning a lab.
        pod
            Name of the pod.
        namespace
            Namespace of the pod.
        start_progress
            Progress percentage to start at when watching pod startup events.
        end_progress
            Progress percentage to stop at when the spawn is complete.

        Raises
        ------
        KubernetesError
            Raised if there is an API error watching events.
        """
        progress = start_progress
        async for event in self._kubernetes.watch_pod_events(pod, namespace):
            await self.publish_event(username, event, progress)

            # We don't know how many startup events we'll see, so we
            # will do the same thing Kubespawner does and move
            # one-third closer to the end of the percentage region
            # each time.
            progress = int(progress + (end_progress - progress) / 3)

    async def _monitor_spawn(
        self,
        *,
        username: str,
        start_progress: int,
        end_progress: int,
        spawner: Optional[Callable[[], Awaitable[str]]] = None,
        internal_url: Optional[str] = None,
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
            Kubernetes objects for the lab and determining the internal URL.
            Either this or ``internal_url`` must be set.
        internal_url
            Internal URL of the lab. Set this instead of ``spawner`` if the
            lab objects have already been created and we only need to wait for
            the lab pod to become ready.
        start_progress
            Progress percentage to start at when watching pod startup events.
        end_progress
            Progress percentage to stop at when the spawn is complete.

        Raises
        ------
        RuntimeError
            Raised if neither ``internal_url`` nor ``spawner`` is set.
        """
        pod = f"{username}-nb"
        namespace = self._builder.namespace_for_user(username)
        logger = self._logger.bind(
            user=username, name=pod, namespace=namespace
        )
        start = current_datetime()
        timeout = self._config.spawn_timeout.total_seconds()
        try:
            async with asyncio.timeout(timeout):
                event_task = asyncio.create_task(
                    self._reflect_events(
                        username=username,
                        pod=pod,
                        namespace=namespace,
                        start_progress=start_progress,
                        end_progress=end_progress,
                    )
                )
                if not internal_url:
                    if not spawner:
                        msg = "Neither internal_url nor spawner provided"
                        raise RuntimeError(msg)
                    internal_url = await spawner()
                await self._kubernetes.wait_for_pod_start(pod, namespace)
        except TimeoutError:
            delay = int((current_datetime() - start).total_seconds())
            msg = f"Lab creation timed out after {delay}s"
            logger.error(msg)
            await self.publish_error(username, msg, fatal=True)
        except Exception as e:
            logger.exception("Lab creation failed")
            if self._slack:
                if isinstance(e, SlackException):
                    e.user = username
                    await self._slack.post_exception(e)
                else:
                    await self._slack.post_uncaught_exception(e)
            await self.publish_error(username, str(e), fatal=True)
        else:
            msg = f"Lab Kubernetes pod started for {username}"
            completion_event = Event(message=msg, type=EventType.COMPLETE)
            await self._add_event(username, completion_event)
            self._labs[username].state.status = LabStatus.RUNNING
            self._labs[username].state.internal_url = internal_url
            logger.info("Lab created")
        finally:
            event_task.cancel()
            try:
                await event_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.exception("Error watching Kubernetes pod events")
                if self._slack:
                    if isinstance(e, SlackException):
                        e.user = username
                        await self._slack.post_exception(e)
                    else:
                        await self._slack.post_uncaught_exception(e)
            self._spawner_done.set()

    async def _recreate_lab_state(self, username: str) -> UserLabState | None:
        """Recreate user lab state from Kubernetes.

        Read the objects from an existing Kubernetes lab namespace and from
        them reconstruct the user's lab state. This is used during
        reconciliation and allows us to recreate internal state from whatever
        currently exists in Kubernetes when the lab controller is restarted.

        Parameters
        ----------
        username
            User whose lab state should be recreated.

        Returns
        -------
        UserLabState or None
            Recreated lab state, or `None` if the user's lab environment did
            not exist or could not be parsed.

        Raises
        ------
        KubernetesError
            Raised if Kubernetes API calls fail for reasons other than the
            resources not existing.
        """
        env_name = f"{username}-nb-env"
        pod_name = f"{username}-nb"
        quota_name = f"{username}-nb"
        namespace = f"{self._config.namespace_prefix}-{username}"
        logger = self._logger.bind(user=username, namespace=namespace)

        # Retrieve objects from Kubernetes.
        env_map = await self._kubernetes.get_config_map(env_name, namespace)
        pod = await self._kubernetes.get_pod(pod_name, namespace)
        quota = await self._kubernetes.get_quota(quota_name, namespace)

        # If the ConfigMap or Pod don't exist, we don't have enough
        # information to recreate state and will have to delete the namespace
        # entirely.
        if not env_map:
            msg = f"No {env_name} ConfigMap for {username}"
            logger.warning(msg, name=env_name)
            return None
        env = env_map.data
        if not pod:
            msg = f"No {pod_name} Pod for {username}"
            self._logger.warning(msg, name=pod_name)
            return None

        # Gather the necessary information from the pod. If anything is
        # missing or in an unexpected format, log an error and return None.
        try:
            lab_container = None
            for container in pod.spec.containers:
                if container.name == "notebook":
                    lab_container = container
                    break
            if not lab_container:
                raise ValueError('No container named "notebook"')
            resources = LabResources(
                limits=ResourceQuantity(
                    cpu=float(env["CPU_LIMIT"]),
                    memory=int(env["MEM_LIMIT"]),
                ),
                requests=ResourceQuantity(
                    cpu=float(env["CPU_GUARANTEE"]),
                    memory=int(env["MEM_GUARANTEE"]),
                ),
            )
            options = UserOptions(
                image_list=env["JUPYTER_IMAGE_SPEC"],
                size=self._size_manager.size_from_resources(resources),
                enable_debug=env.get("DEBUG", "FALSE") == "TRUE",
                reset_user_env=env.get("RESET_USER_ENV", "FALSE") == "TRUE",
            )
            internal_url = self._builder.build_internal_url(username, env)
            user = UserInfo(
                username=username,
                name=pod.metadata.annotations.get("nublado.lsst.io/user-name"),
                uid=lab_container.security_context.run_as_user,
                gid=lab_container.security_context.run_as_group,
                groups=self._recreate_groups(pod),
            )
            return UserLabState(
                user=user,
                options=options,
                env=self._builder.recreate_env(env),
                status=LabStatus.from_phase(pod.status.phase),
                pod=PodState.PRESENT,
                internal_url=internal_url,
                resources=resources,
                quota=self._recreate_quota(quota),
            )
        except Exception as e:
            error = f"{type(e).__name__}: {str(e)}"
            logger.error(f"Invalid lab environment for {username}: {error}")
            return None

    def _recreate_groups(self, pod: V1Pod) -> list[UserGroup]:
        """Recreate user group information from a Kubernetes ``Pod``.

        The GIDs are stored as supplemental groups, but the names of the
        groups go into the templating of the :file:`/etc/group` file and
        aren't easy to extract. We therefore add a serialized version of the
        group list as a pod annotation so that we can recover it during
        reconciliation.

        Parameters
        ----------
        pod
            User lab pod.

        Returns
        -------
        list of UserGroup
            User's group information.
        """
        annotation = "nublado.lsst.io/user-groups"
        groups = json.loads(pod.metadata.annotations.get(annotation, "[]"))
        return [UserGroup.parse_obj(g) for g in groups]

    def _recreate_quota(
        self, resource_quota: V1ResourceQuota | None
    ) -> ResourceQuantity | None:
        """Recreate the user's quota information from Kuberentes.

        Parameters
        ----------
        resource_quota
            Kubernetes ``ResourceQuota`` object, or `None` if there was none
            for this user.

        Returns
        -------
        ResourceQuantity or None
            Corresponding user quota object, or `None` if no resource quota
            was found in Kubernetes.
        """
        if not resource_quota:
            return None
        return ResourceQuantity(
            cpu=float(resource_quota.spec.hard["limits.cpu"]),
            memory=int(resource_quota.spec.hard["limits.memory"]),
        )

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
                if state.task and state.task.done():
                    spawner = state.task
                    state.task = None
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
        prefix = self._config.namespace_prefix
        to_monitor = []

        # Gather information about all extant Kubernetes namespaces.
        observed = {}
        for namespace in await self._kubernetes.list_namespaces(prefix):
            username = namespace.removeprefix(f"{prefix}-")
            if username in self._labs and self._labs[username].task:
                continue
            state = await self._recreate_lab_state(username)
            if state:
                observed[username] = state
            else:
                if username in self._labs:
                    continue
                msg = f"Deleting incomplete namespace {namespace}"
                self._logger.warning(msg, user=username)
                await self._kubernetes.delete_namespace(namespace)

        # If the set of users we expected to see changed during
        # reconciliation, we may be running into all sorts of race conditions.
        # Just skip this background update; we'll catch any inconsistencies
        # the next time around.
        if set(self._labs.keys()) != known_users:
            msg = "Known users changed during reconciliation, skipping"
            self._logger.info(msg)
            return

        # First pass: check all users already recorded in internal state
        # against Kubernetes and correct them (or remove them) if needed.
        for username, lab in list(self._labs.items()):
            if lab.task:
                continue
            if lab.state.status == LabStatus.FAILED:
                continue
            if username not in observed:
                msg = f"Expected user {username} not found in Kubernetes"
                self._logger.warning(msg)
                self._labs[username].state.status = LabStatus.FAILED
            else:
                observed_state = observed[username]
                if observed_state.status != lab.state.status:
                    self._logger.warning(
                        f"Expected status for {username} is"
                        f" {lab.state.status}, but observed status is"
                        f" {observed_state.status}"
                    )
                    lab.state.status = observed_state.status

                # If we discovered the pod was actually in pending state, kick
                # off a monitoring job to wait for it to become ready and
                # handle timeouts if it never does.
                if observed_state.status == LabStatus.PENDING:
                    to_monitor.append(observed_state)

        # Second pass: take observed state and create any missing internal
        # state. This is the normal case after a restart of the lab
        # controller.
        for username in set(observed.keys()) - known_users:
            if username not in self._labs:
                msg = f"Creating record for user {username} from Kubernetes"
                self._logger.info(msg)
                self._labs[username] = UserLab(state=observed[username])
                if observed[username].status == LabStatus.PENDING:
                    to_monitor.append(observed[username])

        # If we discovered any pods unexpectedly in the pending state, kick
        # off monitoring jobs to wait for them to become ready and handle
        # timeouts if they never do.
        for pending in to_monitor:
            username = pending.user.username
            await self._clear_events(self._labs[username])
            msg = f"Monitoring in-progress lab creation for {username}"
            await self.publish_event(username, msg, 1)
            self._labs[username].task = asyncio.create_task(
                self._monitor_spawn(
                    username=username,
                    internal_url=pending.internal_url,
                    start_progress=25,
                    end_progress=75,
                )
            )

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
