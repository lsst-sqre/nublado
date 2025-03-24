"""Service to manage user lab environments."""

from __future__ import annotations

import asyncio
import contextlib
from base64 import b64encode
from collections.abc import AsyncIterator, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Self

from safir.asyncio import AsyncMultiQueue
from safir.slack.blockkit import (
    SlackException,
)
from safir.slack.webhook import SlackWebhookClient
from structlog.stdlib import BoundLogger

from ..config import LabConfig
from ..constants import KUBERNETES_REQUEST_TIMEOUT
from ..events import (
    ActiveLabsEvent,
    LabEvents,
    SpawnFailureEvent,
    SpawnSuccessEvent,
)
from ..exceptions import (
    ControllerTimeoutError,
    InsufficientQuotaError,
    InvalidLabSizeError,
    KubernetesError,
    LabDeletionError,
    LabExistsError,
    MissingSecretError,
    NoOperationError,
    OperationConflictError,
    PermissionDeniedError,
    UnknownUserError,
)
from ..models.domain.docker import DockerReference
from ..models.domain.gafaelfawr import GafaelfawrUser
from ..models.domain.lab import Event, EventType, LabObjectNames
from ..models.domain.rspimage import RSPImage
from ..models.v1.lab import LabSpecification, LabState, LabStatus
from ..storage.kubernetes.lab import LabStorage
from ..storage.metadata import MetadataStorage
from ..timeout import Timeout
from .builder.lab import LabBuilder
from .image import ImageService

__all__ = ["LabManager"]


@dataclass
class _State:
    """Collects all internal state for a user's lab."""

    monitor: _LabMonitor
    """Monitor for any in-progress lab operation."""

    state: LabState | None = None
    """Current state of the lab, in the form returned by status routes."""

    events: AsyncMultiQueue[Event] = field(default_factory=AsyncMultiQueue)
    """Events from the current or most recent lab operation."""

    last_modified: datetime = field(
        default_factory=lambda: datetime.now(tz=UTC)
    )
    """Last time the state was changed.

    This is required to prevent race conditions such as the following:

    #. New lab starts being created.
    #. Reconcile gathers information about the partially created lab and finds
       that it is incomplete.
    #. Lab finishes being spawned and the operation ends.
    #. Reconcile checks to see if there is an operation in progress, sees that
       there isn't, and therefore thinks it's safe to delete supposedly
       malformed lab.

    With this setting, reconcile can check if either a lab operation is in
    progress or if an operation completed since reconcile started and skip the
    reconcile either way.
    """

    def modified_since(self, date: datetime) -> bool:
        """Whether the lab state has been modified since the given time.

        Any lab that has a current in-progress operation is counted as
        modified.

        Parameters
        ----------
        date
            Reference time.

        Returns
        -------
        bool
            `True` if the internal last-modified time is after the provided
            time, `False` otherwise.
        """
        return bool(self.monitor.in_progress or self.last_modified > date)


class _LabOperation(Enum):
    """Possible operations on a lab that could be in progress."""

    SPAWN = "spawn"
    DELETE = "delete"


@dataclass
class _Operation:
    """A requested operation on a user lab."""

    operation: _LabOperation
    """Operation in progress."""

    coro: Coroutine[None, None, None]
    """Coroutine that performs the action of the operation."""

    state: LabState
    """Lab state associated with the operation."""

    events: AsyncMultiQueue[Event]
    """Event queue associated with the operation."""

    started: datetime
    """When the operation was started."""


@dataclass
class _RunningOperation(_Operation):
    """Tracks the state of a lab operation in progress.

    We want to track several things about a running lab operation together, so
    group them into a data structure to guarantee they cannot get out of sync.
    Only one of these may exist at a time for a given `_LabMonitor` instance.
    """

    task: asyncio.Task[None]
    """Task that is monitoring that operation."""

    complete: asyncio.Event = field(default_factory=asyncio.Event)
    """Wait on this event to wait for the completion of the task."""

    @classmethod
    def start(
        cls, operation: _Operation, monitor: Coroutine[None, None, None]
    ) -> Self:
        """Start an operation.

        Parameters
        ----------
        operation
            Operation to start.
        monitor
            Monitoring task that is watching the underlying coroutine.

        Returns
        -------
        _RunningOperation
            Running operation based on the provided requested operation.
        """
        task = asyncio.create_task(monitor)
        return cls(
            task=task,
            operation=operation.operation,
            coro=operation.coro,
            state=operation.state,
            events=operation.events,
            started=operation.started,
        )


class LabManager:
    """Manage user labs.

    The lab manager is a process singleton that manages user labs. This
    includes spawning them, deleting them, and tracking their state.

    Parameters
    ----------
    config
        Configuration for user labs.
    image_service
        Tracks all available images and resolves the parameters of a request
        for a new lab to a specific Docker image.
    lab_builder
        Builder for Kubernetes lab objects.
    metadata_storage
        Storage for metadata about the running controller.
    lab_storage
        Kubernetes storage layer for user labs.
    events
        Metrics events publishers.
    slack_client
        Optional Slack webhook client for alerts.
    logger
        Logger to use.
    """

    def __init__(
        self,
        *,
        config: LabConfig,
        image_service: ImageService,
        lab_builder: LabBuilder,
        metadata_storage: MetadataStorage,
        lab_storage: LabStorage,
        events: LabEvents,
        slack_client: SlackWebhookClient | None,
        logger: BoundLogger,
    ) -> None:
        self._config = config
        self._image_service = image_service
        self._builder = lab_builder
        self._metadata = metadata_storage
        self._storage = lab_storage
        self._events = events
        self._slack = slack_client
        self._logger = logger

        # Mapping of usernames to internal lab state.
        self._labs: dict[str, _State] = {}

        # Triggered when any background thread monitoring spawn progress
        # completes. This has to be triggered manually, so there must be a
        # top-level exception handler for each spawner task that ensures it is
        # set when the spawner task exits for any reason. Otherwise, the
        # reaper task may never realize a spawner has finished and wake up.
        self._spawner_done = asyncio.Event()

    async def create_lab(
        self, user: GafaelfawrUser, spec: LabSpecification
    ) -> None:
        """Schedules creation of user lab objects/resources.

        Parameters
        ----------
        user
            User for whom the lab is being created.
        spec
            Specification for lab to spawn.

        Raises
        ------
        InvalidDockerReferenceError
            Raised if the Docker image reference in the lab specification is
            invalid.
        InvalidLabSizeError
            Raised if the requested lab size is not one of the configured
            sizes.
        LabExistsError
            Raised if this user already has a lab.
        OperationConflictError
            Raised if some other operation (either spawn or delete) is already
            in progress on this user's lab.
        PermissionDeniedError
            Raised if the user's quota does not allow them to spawn labs.
        """
        self._check_quota(user)

        # If the user was not previously seen, set up their data structure and
        # monitor class.
        username = user.username
        if username not in self._labs:
            monitor = _LabMonitor(
                username=username,
                events=self._events,
                slack_client=self._slack,
                logger=self._logger,
            )
            self._labs[username] = _State(monitor=monitor)

        # Determine the image to use for the lab.
        selection = spec.options.image_list or spec.options.image_dropdown
        if selection:
            reference = DockerReference.from_str(selection)
            image = await self._image_service.image_for_reference(reference)
        elif spec.options.image_class:
            image_class = spec.options.image_class
            image = self._image_service.image_for_class(image_class)
        elif spec.options.image_tag:
            tag = spec.options.image_tag
            image = await self._image_service.image_for_tag_name(tag)

        # Determine the resources to assign to the lab.
        try:
            size = self._config.get_size_definition(spec.options.size)
        except KeyError as e:
            raise InvalidLabSizeError(spec.options.size) from e
        if user.quota and user.quota.notebook:
            quota = user.quota.notebook
            if quota.memory_bytes < size.memory_bytes or quota.cpu < size.cpu:
                msg = "Insufficient quota to spawn requested lab"
                raise InsufficientQuotaError(msg)
        resources = size.to_lab_resources()

        # Check to see if the lab already exists. If so, but it is in a failed
        # state, we will delete the previous lab first.
        state = await self._get_lab_state_from_kubernetes(user.username)
        delete_first = bool(state and not state.is_running)

        # If there is any operation already in progress, raise an error.
        # Similarly, if the lab already exists and is not in a failed or
        # terminated state, raise an error.
        #
        # This must be done after any other preliminaries that may yield
        # control, to ensure that state doesn't change between our check and
        # starting a new operation.
        lab = self._labs[username]
        if lab.monitor.in_progress:
            operation_type = lab.monitor.in_progress.value
            self._logger.warning(
                "Operation in progress",
                username=username,
                operation=operation_type,
            )
            msg = f"Operation in progress for {username}: {operation_type}"
            raise OperationConflictError(msg)
        if lab.state and not delete_first:
            self._logger.warning(
                "Lab already exists",
                username=username,
                status=lab.state.status.value,
            )
            raise LabExistsError(f"Lab already exists for {username}")

        # Kick off the spawn and hand it off to the monitor to watch.
        #
        # Since we may yield control when start_spawn is called but before it
        # can run, store the new lab state *after* the monitor has
        # successfully started. If the user has no lab and two spawns are
        # started at the same time, the second will raise an
        # OperationConflictError. This ordering ensures that only the
        # successful call is able to update the user's lab state.
        lab.events.clear()
        state = LabState.from_request(
            user=user, spec=spec, image=image, resources=resources
        )
        timeout = Timeout("Lab spawn", self._config.spawn_timeout, username)
        spawner = self._spawn_lab(
            user=user,
            state=state,
            spec=spec,
            image=image,
            events=lab.events,
            timeout=timeout,
            delete_first=delete_first,
        )
        operation = _Operation(
            operation=_LabOperation.SPAWN,
            coro=spawner,
            state=state,
            events=lab.events,
            started=datetime.now(tz=UTC),
        )
        await lab.monitor.monitor(operation, timeout, self._spawner_done)
        lab.state = state

    async def delete_lab(self, username: str) -> None:
        """Delete the lab environment for the given user.

        This may be called multiple times for the same user, and all deletions
        will wait for the same underlying Kubernetes operation.

        Parameters
        ----------
        username
            Username whose environment should be deleted.

        Raises
        ------
        LabDeletionError
            Raised if the lab deletion failed for any other reason.
        OperationConflictError
            Raised if another operation is already in progress.
        UnknownUserError
            Raised if no lab currently exists for this user.
        """
        if username not in self._labs:
            raise UnknownUserError(f"Unknown user {username}")
        lab = self._labs[username]
        if not lab.state:
            raise UnknownUserError(f"Unknown user {username}")

        # There are three possible cases.
        #
        # 1. A deletion is already in progress, in which case we want to wait
        #    on it with everyone else who is monitoring the deletion.
        # 2. No operation is in progress, in which case we start the deletion
        #    and take responsibility for clearing the lab state when it
        #    finishes.
        # 3. A spawn is already in progress, in which case we want to abort
        #    that spawn and then do a normal delete to remove any remnants.
        #
        # Also handle the currently-impossible fourth case of some other
        # operation in progress. There currently is no other operation, but
        # do something safe in case one appears in the future.
        if lab.monitor.in_progress == _LabOperation.DELETE:
            await lab.monitor.wait()
        elif lab.monitor.in_progress in (_LabOperation.SPAWN, None):
            if lab.monitor.in_progress == _LabOperation.SPAWN:
                await lab.monitor.cancel()
            lab.events.clear()

            # A delete may have been in progress and just finished while we
            # were waiting on cancel, thus deleting the lab state out from
            # under us.
            if not lab.state:
                raise UnknownUserError(f"Unknown user {username}")

            # Move forward with a delete operation.
            self._builder.build_object_names(username)
            lab.state.status = LabStatus.TERMINATING
            lab.state.internal_url = None
            timeout = Timeout(
                "Delete lab", self._config.delete_timeout, username
            )
            action = self._delete_lab(username, lab.state, lab.events, timeout)
            operation = _Operation(
                operation=_LabOperation.DELETE,
                coro=action,
                state=lab.state,
                events=lab.events,
                started=datetime.now(tz=UTC),
            )
            await lab.monitor.monitor(operation, timeout)
            await lab.monitor.wait()
            lab.last_modified = datetime.now(tz=UTC)
            if lab.state.status == LabStatus.TERMINATED:
                lab.state = None
        else:
            raise OperationConflictError(username)
        if lab.state and lab.state.status != LabStatus.TERMINATED:
            msg = f"Deleting lab for {username} failed"
            raise LabDeletionError(msg, username)

    def events_for_user(self, username: str) -> AsyncIterator[bytes]:
        """Construct an iterator over the events for a user.

        Parameters
        ----------
        username
            Username for which to retrieve events.

        Yields
        ------
        bytes
            Next encoded server-sent event.

        Raises
        ------
        UnknownUserError
            Raised if there is no event stream for this user.
        """
        if username not in self._labs:
            raise UnknownUserError(f"Unknown user {username}")

        async def iterator() -> AsyncIterator[bytes]:
            async for event in self._labs[username].events:
                yield event.to_sse().encode()

        return iterator()

    async def get_lab_state(self, username: str) -> LabState | None:
        """Get lab state for a user.

        This method underlies the API called by JupyterHub to track whether
        the user's lab still exists. Originally, it would query Kubernetes for
        every request from JupyterHub, but we found this saturated the
        Kubernetes control plane when large numbers of labs were running. It
        therefore responds based on internal state and relies on periodic
        reconciliation to update state from Kubernetes.

        Parameters
        ----------
        username
            Username to retrieve lab state for.

        Returns
        -------
        LabState or None
            Lab state for that user, or `None` if that user doesn't have a
            lab.

        Raises
        ------
        UnknownUserError
            Raised if the given user has no lab.
        """
        if username not in self._labs:
            return None
        return self._labs[username].state

    async def list_lab_users(self, *, only_running: bool = False) -> list[str]:
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
                if s.state and s.state.status == LabStatus.RUNNING
            ]
        else:
            return [u for u, s in self._labs.items() if s.state]

    async def reap_spawners(self) -> None:
        """Wait for spawner tasks to complete and record their status.

        When a user spawns a lab, the lab controller creates a background task
        to create the Kubernetes objects and then wait for the pod to finish
        starting. Something needs to await those tasks so that they can be
        cleanly finalized and to catch any uncaught exceptions. That function
        is performed by a background task running this method.

        This method is also responsible for updating the last modified time in
        the lab state.

        Notes
        -----
        Doing this properly is a bit tricky, since we have to avoid both
        busy-waiting when no operations are in progress and not reaping
        anything if one operation keeps running forever. The approach used
        here is to have every spawn set the ``_spawner_done`` `asyncio.Event`
        when it is complete, and use that as a trigger for doing a reaper
        pass. Deletes do not do this since they're normally awaited by the
        caller and thus don't need to be reaped separately.
        """
        while True:
            await self._spawner_done.wait()
            self._spawner_done.clear()
            for username, lab in self._labs.items():
                if lab.monitor.in_progress and lab.monitor.is_done():
                    try:
                        await lab.monitor.wait()
                        lab.last_modified = datetime.now(tz=UTC)
                    except NoOperationError:
                        # There is a race condition with deletes, since the
                        # task doing the delete kicks it off and then
                        # immediately waits for its completion. We may
                        # discover the completed task right before that wait
                        # wakes up and reaps it, and then have no task by the
                        # time we call wait ourselves. This should be harmless
                        # and ignorable.
                        pass
                    except Exception as e:
                        lab.last_modified = datetime.now(tz=UTC)
                        msg = "Uncaught exception in monitor thread"
                        self._logger.exception(msg, user=username)
                        await self._maybe_post_slack_exception(e, username)
                        if lab.state:
                            lab.state.status = LabStatus.FAILED

    async def reconcile(self) -> None:
        """Reconcile user lab state with Kubernetes.

        This method is called on startup and then periodically from a
        background thread to check Kubernetes and ensure the in-memory record
        of the user's lab state matches reality. On startup, it also needs to
        recreate the internal state from the contents of Kubernetes.

        This method is also responsible for logging the current number of
        active labs.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        self._logger.info("Reconciling user lab state with Kubernetes")
        start = datetime.now(tz=UTC)

        # Gather information about all extant Kubernetes namespaces and delete
        # any malformed namespaces for which no operation is in progress.
        observed = await self._gather_current_state(start)

        # First pass: check all users already recorded in internal state
        # against Kubernetes and correct them (or remove them) if needed.
        to_monitor = self._reconcile_known_users(observed, start)

        # Second pass: take observed state and create any missing internal
        # state. This is the normal case after a restart of the lab
        # controller.
        for username in set(observed.keys()) - set(self._labs.keys()):
            msg = f"Creating record for user {username} from Kubernetes"
            self._logger.info(msg)
            self._labs[username] = _State(
                state=observed[username],
                monitor=_LabMonitor(
                    username=username,
                    events=self._events,
                    slack_client=self._slack,
                    logger=self._logger,
                ),
            )
            if observed[username].status == LabStatus.PENDING:
                to_monitor.add(username)

        # If we discovered any pods unexpectedly in the pending state, kick
        # off monitoring jobs to wait for them to become ready and handle
        # timeouts if they never do. We've now fixed internal state, so it's
        # safe to do asyncio operations again.
        for username in sorted(to_monitor):
            await self._monitor_pending_spawn(username)

        # For all labs in failed or terminated state (spawn failed, killed by
        # the idle culler, killed by the OOM killer, etc.), clean up the lab
        # as long as the user hasn't started some other operation in the
        # meantime.
        await self._delete_completed_labs()

        # Finally, count the active labs and log a metric.
        count = 0
        for state in self._labs.values():
            if state.state and state.state.status == LabStatus.RUNNING:
                count += 1
        await self._events.active.publish(ActiveLabsEvent(count=count))

    async def stop_monitor_tasks(self) -> None:
        """Stop any tasks that are waiting for labs to spawn."""
        self._logger.info("Stopping spawning monitor tasks")
        labs = self._labs
        self._labs = {}
        for state in labs.values():
            await state.monitor.cancel()

    def _check_quota(self, user: GafaelfawrUser) -> None:
        """Check if lab spawning is allowed by the user's quota.

        Parameters
        ----------
        user
            User information for the user attempting to spawn a lab.

        Raises
        ------
        PermissionDeniedError
            Raised if the user's quota does not allow them to spawn labs.
        """
        if not user.quota or not user.quota.notebook:
            return
        if not user.quota.notebook.spawn:
            raise PermissionDeniedError("Spawning a notebook is not permitted")

    async def _delete_lab(
        self,
        username: str,
        state: LabState,
        events: AsyncMultiQueue[Event],
        timeout: Timeout,
        *,
        start_progress: int = 25,
        end_progress: int = 100,
    ) -> None:
        """Delete the user's lab and namespace.

        Parameters
        ----------
        username
            Username of user whose lab should be deleted.
        state
            Lab state.
        events
            Event queue to update with progress.
        timeout
            Timeout on operation.
        start_progress
            Starting progress for progress events. This is different when
            deleting a lab in response to an API request and deleting a failed
            lab at the start of spawning a new one.
        end_progress
            Ending progress for progress events. This is different when
            deleting a lab in response to an API request and deleting a failed
            lab at the start of spawning a new one.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        names = self._builder.build_object_names(username)
        msg = "Shutting down Kubernetes pod"
        progress = start_progress
        events.put(Event(type=EventType.INFO, message=msg, progress=progress))
        await self._storage.delete_pod(names, timeout)

        progress += int((end_progress - start_progress) / 2)
        msg = "Deleting user namespace"
        events.put(Event(type=EventType.INFO, message=msg, progress=progress))
        await self._storage.delete_namespace(names.namespace, timeout)

        self._logger.info("Lab deleted", username=username)
        progress = end_progress
        msg = f"Lab for {username} deleted"
        events.put(Event(type=EventType.INFO, message=msg, progress=progress))
        state.status = LabStatus.TERMINATED

    async def _delete_completed_labs(self) -> None:
        """Delete all labs that have stopped running.

        Run from the background reconciliation thread, which will have just
        updated the lab status in our internal state. Any labs in a terminated
        state are no longer running and should be garbage-collected, as long
        as the user hasn't already started a new operation on that lab.
        """
        all_labs = list(self._labs.items())
        for username, lab in all_labs:
            if lab.state and not lab.state.is_running:
                if not lab.monitor.in_progress:
                    with contextlib.suppress(UnknownUserError):
                        await self.delete_lab(username)

    async def _gather_current_state(
        self, cutoff: datetime
    ) -> dict[str, LabState]:
        """Gather lab state from extant Kubernetes resources.

        Called during reconciliation, this method determines the current lab
        state by scanning the resources in Kubernetes. Malformed labs that do
        not have an existing entry in our state mapping will be deleted.

        Parameters
        ----------
        cutoff
            Do not delete incomplete namespaces for users modified after this
            date, since our data may be stale.

        Returns
        -------
        dict of LabState
            Dictionary mapping usernames to the discovered lab state.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        prefix = self._config.namespace_prefix + "-"

        observed = {}
        timeout = Timeout("List namespaces", KUBERNETES_REQUEST_TIMEOUT)
        for namespace in await self._storage.list_namespaces(prefix, timeout):
            username = namespace.removeprefix(prefix)
            names = self._builder.build_object_names(username)
            timeout = Timeout("Read lab objects", KUBERNETES_REQUEST_TIMEOUT)
            objects = await self._storage.read_lab_objects(names, timeout)
            state = await self._builder.recreate_lab_state(username, objects)

            # Only delete malformed labs with no entry or that have not been
            # modified since we started gathering data.
            lab = self._labs.get(username)
            if state:
                observed[username] = state
            elif not lab or not lab.modified_since(cutoff):
                msg = "Deleting incomplete namespace"
                self._logger.warning(msg, user=username, namespace=namespace)
                timeout = Timeout(msg, KUBERNETES_REQUEST_TIMEOUT)
                await self._storage.delete_namespace(namespace, timeout)
        return observed

    async def _gather_secret_data(
        self, user: GafaelfawrUser, timeout: Timeout
    ) -> dict[str, str]:
        """Gather the key/value pair secret data used by the lab.

        Read the secrets specified in the lab configuration, extract the keys
        and values requested by the configuration, and assemble a dictionary
        of secrets that the lab should receive.

        Parameters
        ----------
        user
            Authenticated Gafaelfawr user.
        timeout
            Total timeout for the lab spawn.

        Returns
        -------
        dict of str
            Secret data for the lab.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        MissingSecretError
            Raised if a secret does not exist.
        """
        secret_names = {s.secret_name for s in self._config.secrets}
        namespace = self._metadata.namespace
        secrets = {
            n: await self._storage.read_secret(n, namespace, timeout)
            for n in sorted(secret_names)
        }

        # Now, construct the data for the user's lab secret.
        data = {}
        for spec in self._config.secrets:
            key = spec.secret_key
            if key not in secrets[spec.secret_name].data:
                namespace = self._metadata.namespace
                raise MissingSecretError(spec.secret_name, namespace, key)
            if key in data:
                # Conflict with another secret. Should be impossible since the
                # validator on our configuration enforces no conflicts.
                raise RuntimeError(f"Duplicate secret key {key}")
            data[key] = secrets[spec.secret_name].data[key]

        # Add the user's token and return the results.
        data["token"] = b64encode(user.token.encode()).decode()
        return data

    async def _get_lab_state_from_kubernetes(
        self, username: str
    ) -> LabState | None:
        """Get lab state for a user from Kubernetes.

        This method underlies the API called by JupyterHub to track whether
        the user's lab still exists. It should be used instead of
        `get_lab_state` when we should not trust the in-memory data
        structures and should verify the lab state directly, such as during
        spawn.

        Parameters
        ----------
        username
            Username to retrieve lab state for.

        Returns
        -------
        LabState or None
            Lab state for that user, or `None` if that user doesn't have a
            lab.

        Raises
        ------
        UnknownUserError
            Raised if the given user has no lab.
        """
        if username not in self._labs:
            return None

        # Grab a copy of the lab state, since we're going to make async calls
        # and the state may be changed out from under us via a delete and
        # spawn. (Unlikely that it will happen that fast, but possible.)
        state = self._labs[username].state
        if not state:
            return None

        # Ask Kubernetes for the current phase so that we catch pods that have
        # been evicted or shut down behind our back by the Kubernetes cluster.
        names = self._builder.build_object_names(username)
        timeout = Timeout(
            "Get pod phase", KUBERNETES_REQUEST_TIMEOUT, username
        )
        try:
            phase = await self._storage.read_pod_phase(names, timeout)
        except KubernetesError as e:
            self._logger.exception(
                "Cannot get pod phase",
                user=username,
                name=names.pod,
                namespace=names.namespace,
                kind="Pod",
            )
            await self._maybe_post_slack_exception(e, username)

            # Two options here: pessimistically assume the lab is in a failed
            # state, or optimistically assume that our current in-memory data
            # is correct. Given that we refresh state in the background
            # continuously, go with optimism; we'll update with pessimism if
            # we can ever reach Kubernetes, and telling JupyterHub to go ahead
            # and try to send the user to the lab seems like the right move.
            return state
        except ControllerTimeoutError as e:
            self._logger.exception("Timeout reading pod phase", user=username)
            await self._maybe_post_slack_exception(e, username)

            # As above, optimistically assume the best.
            return state

        # If the pod is missing, set the state to failed. Also set the state
        # to terminated or failed if we thought the pod was running but it's
        # in some other state. Otherwise, go with our current state.
        if phase is None:
            state.status = LabStatus.FAILED
        elif state.status == LabStatus.RUNNING:
            state.status = LabStatus.from_phase(phase)
        return state

    async def _maybe_post_slack_exception(
        self, exc: Exception, username: str
    ) -> None:
        """Post an exception to Slack if Slack reporting is configured.

        Parameters
        ----------
        exc
            Exception to report.
        username
            Username that triggered the exception.
        """
        if not self._slack:
            return
        if isinstance(exc, SlackException):
            exc.user = username
            await self._slack.post_exception(exc)
        else:
            await self._slack.post_uncaught_exception(exc)

    async def _monitor_pending_spawn(self, username: str) -> None:
        """Watch pending spawns of labs for the provided users.

        This is called by the reconciliation task to monitor in-progress lab
        spawns that we didn't start ourselves, such as after a controller
        restart. We may be racing with other operations, so always check first
        that no other operation is in progress.

        Parameters
        ----------
        username
            Username whose lab spawn should be monitored. If we're already
            monitoring them or if the lab state does not exist, silently do
            nothing.
        """
        lab = self._labs[username]
        if lab.monitor.in_progress:
            return
        if not lab.state:
            return
        lab.events.clear()
        msg = f"Monitoring in-progress lab creation for {username}"
        lab.events.put(Event(type=EventType.INFO, message=msg, progress=1))
        self._logger.info(msg, user=username)
        timeout = Timeout(
            "In-progress lab spawn", self._config.spawn_timeout, username
        )
        watcher = self._watch_lab_spawn(lab.state, lab.events, timeout)
        operation = _Operation(
            operation=_LabOperation.SPAWN,
            coro=watcher,
            state=lab.state,
            events=lab.events,
            started=datetime.now(tz=UTC),
        )

        # If we raced with some other operation that got there first, they
        # will probably be a delete or spawn with richer context, so we should
        # silently let them win.
        with contextlib.suppress(OperationConflictError):
            await lab.monitor.monitor(operation, timeout, self._spawner_done)

    def _reconcile_known_users(
        self, observed: dict[str, LabState], cutoff: datetime
    ) -> set[str]:
        """Reconcile observed lab state against already-known users.

        Check all users already recorded in internal state against data
        observed from Kubernetes and correct them if needed.

        Parameters
        ----------
        observed
            Observed lab state.
        cutoff
            Do not change labs that have been modified since this date, since
            our gathered data about the lab may be stale.

        Returns
        -------
        set of str
            Usernames of users with pending lab spawns that are not currently
            being monitored and should be.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.

        Notes
        -----
        This method must not be async to ensure that it does not yield control
        to other threads that could change internal state while performing
        this analysis.
        """
        to_monitor = set()
        for username, lab in self._labs.items():
            if not lab.state or lab.modified_since(cutoff):
                continue
            if lab.state.status == LabStatus.FAILED:
                continue
            if username not in observed:
                msg = f"Expected user {username} not found in Kubernetes"
                self._logger.warning(msg)
                lab.state.status = LabStatus.FAILED
            else:
                observed_state = observed[username]
                if observed_state.status == lab.state.status:
                    continue

                # The discovered state was not what we expected. Update our
                # state.
                msg = (
                    f"Expected status is {lab.state.status}, but observed"
                    f" status is {observed_state.status}"
                )
                self._logger.warning(msg, user=username)
                lab.state.status = observed_state.status

                # If we discovered the pod was actually in pending state,
                # kick off a monitoring job to wait for it to become ready
                # and handle timeouts if it never does.
                if observed_state.status == LabStatus.PENDING:
                    to_monitor.add(username)
        return to_monitor

    async def _spawn_lab(
        self,
        *,
        user: GafaelfawrUser,
        state: LabState,
        spec: LabSpecification,
        image: RSPImage,
        events: AsyncMultiQueue[Event],
        timeout: Timeout,
        delete_first: bool = False,
    ) -> None:
        """Do the actual work of spawning a user's lab.

        Runs as a background task and is monitored by a `_LabMonitor`.

        Parameters
        ----------
        state
            Initial state of the lab, which includes the user and the lab
            request.
        spec
            Specification for lab to spawn.
        image
            Image to use for the lab.
        events
            Event queue to which to post spawn events.
        timeout
            Timeout for the lab spawn.
        delete_first
            Whether to delete any existing lab first.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        MissingSecretError
            Raised if one of the secrets required for spawning the lab is
            missing.
        """
        username = state.user.username
        msg = f"Starting lab creation for {username}"
        events.put(Event(type=EventType.INFO, message=msg, progress=1))

        # Delete any existing lab first if needed.
        if delete_first:
            self._logger.info("Deleting existing failed lab")
            msg = f"Deleting existing failed lab for {username}"
            events.put(Event(type=EventType.INFO, message=msg, progress=2))
            await self._delete_lab(
                username,
                state,
                events,
                timeout,
                start_progress=5,
                end_progress=20,
            )
            self._logger.info("Lab deleted")

        # Retrieve the secrets that will be used to construct the lab secret.
        self._logger.info("Retrieving secret data")
        pull_secret = None
        try:
            secret_data = await self._gather_secret_data(user, timeout)
            if self._config.pull_secret:
                name = self._config.pull_secret
                namespace = self._metadata.namespace
                pull_secret = await self._storage.read_secret(
                    name, namespace, timeout
                )
        except MissingSecretError as e:
            e.user = username
            raise

        # Build the objects that make up the user's lab.
        state.status = LabStatus.PENDING
        names = self._builder.build_object_names(username)
        objects = self._builder.build_lab(
            user=user,
            lab=spec,
            image=image,
            secrets=secret_data,
            pull_secret=pull_secret,
        )
        internal_url = self._builder.build_internal_url(username, spec.env)
        self._logger.info("Creating new lab", user=username)

        # Create the namespace, because we can't watch for events until the
        # namespace exists.
        await self._storage.create_namespace(objects, timeout)

        # Monitor for lab events while creating the remaining Kubernetes
        # objects and waiting for the pod to start.
        try:
            watcher = self._watch_spawn_events(names, events, timeout)
            watch_task = asyncio.create_task(watcher)
            await self._storage.create(objects, timeout)
            msg = "Created Kubernetes objects for user lab"
            events.put(Event(type=EventType.INFO, message=msg, progress=30))
            state.internal_url = internal_url
            await self._storage.wait_for_pod_start(
                names.pod, names.namespace, timeout
            )
        finally:
            watch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watch_task
        state.status = LabStatus.RUNNING
        self._logger.info("Lab created", user=username)
        msg = f"Lab Kubernetes pod started for {username}"
        events.put(Event(type=EventType.COMPLETE, message=msg))

    async def _watch_lab_spawn(
        self,
        state: LabState,
        events: AsyncMultiQueue[Event],
        timeout: Timeout,
    ) -> None:
        """Wait for a lab spawn to complete, reflecting Kubernetes events.

        This is run after state reconciliation when finding a lab that is
        fully created and waiting for the pod to start.

        Parameters
        ----------
        state
            Initial state of the lab, which includes the user and the lab
            request.
        events
            Event queue to which to post spawn events.
        timeout
            Timeout for the lab spawn.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        username = state.user.username
        names = self._builder.build_object_names(username)
        name = names.pod
        namespace = names.namespace
        try:
            watcher = self._watch_spawn_events(names, events, timeout)
            watch_task = asyncio.create_task(watcher)
            await self._storage.wait_for_pod_start(name, namespace, timeout)
        finally:
            watch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watch_task
        state.status = LabStatus.RUNNING
        self._logger.info("Lab created", user=username)
        msg = f"Lab Kubernetes pod started for {username}"
        events.put(Event(type=EventType.COMPLETE, message=msg))

    async def _watch_spawn_events(
        self,
        names: LabObjectNames,
        events: AsyncMultiQueue[Event],
        timeout: Timeout,
    ) -> None:
        """Monitor Kubernetes events for a pod.

        Translate these into our internal event structure and add them to the
        event list for this user. Intented to be run as a task and cancelled
        once the pod spawn completes or times out. Moves the progress bar
        between 35% and 75%. The last 25% is reserved for waiting for the lab
        to respond, which is done internally by JupyterHub.

        Watching spawn events is not critical to spawning a lab, so if the
        event watcher fails for any reason, report that error but then swallow
        it and allow the lab to still successfully spawn.

        Parameters
        ----------
        names
            Names of the lab objects.
        events
            Event queue to which to report events.
        timeout
            Timeout for the lab spawn.
        """
        name = names.pod
        namespace = names.namespace
        iterator = self._storage.watch_events(name, namespace, timeout)
        progress = 35
        try:
            async for msg in iterator:
                events.put(
                    Event(type=EventType.INFO, message=msg, progress=progress)
                )
                self._logger.debug(f"Spawning event: {msg}", progress=progress)

                # We don't know how many startup events we'll see, so we will
                # do the same thing Kubespawner does and move one-third closer
                # to 75% each time.
                progress = int(progress + (75 - progress) / 3)
        except KubernetesError as e:
            # Report any failures, but then swallow them and let the event
            # watcher thread silently exit, since watching pod spawn events is
            # not critical to spawning.
            username = names.username
            self._logger.exception("Error watching lab events", user=username)
            await self._maybe_post_slack_exception(e, username)


class _LabMonitor:
    """Monitor lab spawning or deletion.

    When performing an operation on a user's lab, such as spawning or
    deletion, we need to monitor the execution of the operation and usually
    then wait for Kubernetes to finish its work and tell us the operation is
    complete. This class wraps that monitoring, including management of any
    necessary background tasks. It is responsible for updating the
    `~controller.models.v1.lab.LabState` and the user's event stream.

    Only one monitor should be running per user at a time, which is equivalent
    to saying that only one lab operation should be in progress for a given
    user at a time. This class is instantiated once per user.

    Parameters
    ----------
    username
        Username for whom we're monitoring actions.
    events
        Metrics events publishers.
    slack_client
        Optional Slack webhook client for alerts.
    logger
        Logger to use.
    """

    def __init__(
        self,
        *,
        username: str,
        events: LabEvents,
        slack_client: SlackWebhookClient | None,
        logger: BoundLogger,
    ) -> None:
        self._username = username
        self._events = events
        self._slack = slack_client
        self._logger = logger.bind(user=username)

        # If _operation is not None, holds the ongoing operation. _lock
        # protects checks and modifications of _operation.
        self._lock = asyncio.Lock()
        self._operation: _RunningOperation | None = None

    @property
    def in_progress(self) -> _LabOperation | None:
        """Current in-progress lab operation, if any."""
        return self._operation.operation if self._operation else None

    async def cancel(self) -> None:
        """Cancel any existing operation.

        This is called during process shutdown and to abort a spawn in
        progress because a delete request was received. Any operations in
        progress is cancelled, which may strand random lab state that we will
        detect and clean up later.
        """
        async with self._lock:
            if not self._operation:
                return
            if not self._operation.task.done():
                msg = "Operation cancelled"
                event = Event(type=EventType.FAILED, message=msg)
                self._operation.events.put(event)
                operation = self._operation.operation.value
                self._logger.warning(f"Cancelling operation {operation}")
                self._operation.task.cancel("Shutting down")
            try:
                await self._operation.task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                msg = "Uncaught exception in monitor task"
                self._logger.exception(msg, user=self._username)
                await self._maybe_post_slack_exception(e)
            self._operation = None

    def is_done(self) -> bool:
        """Whether the current operation is complete.

        Callers must check that an operation is in progress with the
        ``in_progress`` property first before calling this method.

        Returns
        -------
        bool
            `True` if the operation is complete and is just waiting for its
            status to be collected, `False` if it is still in progress.

        Raises
        ------
        RuntimeError
            Raised if no operation is currently in progress.
        """
        if not self._operation:
            msg = f"No operation in progress for {self._username}"
            raise RuntimeError(msg)
        return self._operation.task.done()

    async def monitor(
        self,
        operation: _Operation,
        timeout: Timeout,
        done_event: asyncio.Event | None = None,
    ) -> None:
        """Monitor a lab operation until it completes, fails, or times out.

        Parameters
        ----------
        operation
            Operation to monitor.
        timeout
            Timeout for operation.
        done_event
            If provided, additional event to notify when the operation is
            complete.

        Raises
        ------
        KubernetesError
            Raised if a Kubernetes error prevented lab deletion.
        OperationConflictError
            Raised if another operation is already in progress.
        """
        async with self._lock:
            if self._operation:
                # If an operation is already running, we will never run the
                # operation's coroutine, so we need to clean it up to avoid
                # Python warnings.
                operation.coro.close()
                raise OperationConflictError(self._username)
            operation.started = datetime.now(tz=UTC)
            monitor = self._monitor_operation(operation, timeout, done_event)
            self._operation = _RunningOperation.start(operation, monitor)

    async def wait(self) -> None:
        """Wait for the current operation to complete.

        Callers must check that an operation is in progress with the
        ``in_progress`` property first before calling this method.

        All callers who get in before the operation is complete will wait for
        the same operation and raise any exceptions that the operation raised.
        Those exceptions will have already been reported to Slack, if
        applicable, and thus should not be reported again.

        Raises
        ------
        Exception
            Raised if the underlying operation raised an exception, re-raising
            whatever that exception is.
        NoOperationError
            Raised if there is no operation in progress.
        """
        async with self._lock:
            if not self._operation:
                msg = f"No operation in progress for {self._username}"
                raise NoOperationError(msg)
            operation = self._operation

        # We now do our waiting on a local reference to the operation. The
        # first waiter to be notified will see that the running operation is
        # equal to the one that just finished and clear the operation, so that
        # subsequent callers will see there is no current operation. Remaining
        # waiters will see either a different operation or None and will do
        # nothing.
        await operation.complete.wait()
        async with self._lock:
            try:
                await operation.task
            except Exception as e:
                msg = "Uncaught exception in monitor task"
                self._logger.exception(msg, user=self._username)
                await self._maybe_post_slack_exception(e)
            if self._operation == operation:
                self._operation = None

    async def _maybe_post_slack_exception(self, exc: Exception) -> None:
        """Post an exception to Slack if Slack reporting is configured.

        Parameters
        ----------
        exc
            Exception to report.
        """
        if not self._slack:
            return
        if isinstance(exc, SlackException):
            exc.user = self._username
            await self._slack.post_exception(exc)
        else:
            await self._slack.post_uncaught_exception(exc)

    async def _monitor_operation(
        self,
        operation: _Operation,
        timeout: Timeout,
        done_event: asyncio.Event | None,
    ) -> None:
        """Monitor an operation on a lab.

        Parameters
        ----------
        operation
            Operation to monitor.
        timeout
            Timeout for operation.
        done_event
            If provided, event to notify when the spawn is complete.
        """
        try:
            async with timeout.enforce():
                await operation.coro
        except Exception as e:
            msg = f"Lab {operation.operation.value} failed"
            self._logger.exception(msg)
            await self._maybe_post_slack_exception(e)
            operation.events.put(Event(type=EventType.ERROR, message=str(e)))
            operation.events.put(Event(type=EventType.FAILED, message=msg))
            operation.state.status = LabStatus.FAILED
            if operation.operation == _LabOperation.SPAWN:
                elapsed = datetime.now(tz=UTC) - operation.started
                failure_event = SpawnFailureEvent(
                    username=self._username,
                    image=operation.state.options.image,
                    cpu_limit=operation.state.resources.limits.cpu,
                    memory_limit=operation.state.resources.limits.memory,
                    elapsed=elapsed,
                )
                await self._events.spawn_failure.publish(failure_event)
        else:
            if operation.operation == _LabOperation.SPAWN:
                elapsed = datetime.now(tz=UTC) - operation.started
                success_event = SpawnSuccessEvent(
                    username=self._username,
                    image=operation.state.options.image,
                    cpu_limit=operation.state.resources.limits.cpu,
                    memory_limit=operation.state.resources.limits.memory,
                    elapsed=elapsed,
                )
                await self._events.spawn_success.publish(success_event)
        finally:
            operation.events.close()
            if self._operation:
                self._operation.complete.set()
            if done_event:
                done_event.set()
