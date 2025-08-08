"""Service to manage administrative filesystem environment."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from datetime import UTC, datetime

from safir.slack.blockkit import SlackException
from safir.slack.webhook import SlackWebhookClient
from structlog.stdlib import BoundLogger

from ..constants import (
    FSADMIN_NAMESPACE,
    FSADMIN_POD_NAME,
    FSADMIN_TIMEOUT,
    KUBERNETES_REQUEST_TIMEOUT,
)
from ..exceptions import (
    UnknownUserError,
)
from ..models.domain.gafaelfawr import GafaelfawrUserInfo
from ..models.domain.kubernetes import PodPhase
from ..models.v1.fileserver import FileserverStatus
from ..storage.kubernetes.fsadmin import FSAdminStorage
from ..timeout import Timeout
from .builder.fsadmin import FSAdminBuilder

__all__ = ["FSAdminManager"]


@dataclass
class _State:
    """State of the fsadmin environment."""

    running: bool
    """Whether the fsadmin pod is running."""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    """Lock to prevent two operations from happening at once."""

    in_progress: bool = False
    """Whether an operation is currently in progress."""

    last_modified: datetime = field(
        default_factory=lambda: datetime.now(tz=UTC)
    )
    """Last time an operation was started or completed.

    This is required to prevent race conditions if multiple users are trying
    to create or delete the fsadmin environment simultaneously.
    """

    def modified_since(self, date: datetime) -> bool:
        """Whether the file server has been modified since the given time.

        Any file server that has a current in-progress operation is counted as
        modified.

        Parameters
        ----------
        date
            Reference time.

        Returns
        -------
        bool
            `True` if the internal last-modified time is after the provided
            time and no operation is in progress, `False` otherwise.
        """
        return bool(self.in_progress or self.last_modified > date)


class FSAdminManager:
    """Manage filesystem admin environment.

    This class is a process-wide singleton that manages the fsadmin
    environment.

    Parameters
    ----------
    fsadmin_builder
        Builder that constructs fsadmin Kubernetes objects.
    fileserver_storage
        Kubernetes storage layer for fsadmin.
    slack_client
        Optional Slack webhook client for alerts.
    logger
        Logger to use.
    """

    def __init__(
        self,
        *,
        fsadmin_builder: FSAdminBuilder,
        fsadmin_storage: FSAdminStorage,
        slack_client: SlackWebhookClient | None,
        logger: BoundLogger,
    ) -> None:
        self._builder = fsadmin_builder
        self._storage = fsadmin_storage
        self._slack = slack_client
        self._logger = logger

    async def create(self) -> None:
        """Ensure the fsadmin environment exists.

        If we don't have a filesystem admin environment, create it.  If we do,
        just return. This gets called by the handler when someone POSTs to the
        ``/fsadmin`` ingress.

        Raises
        ------
        controller.exceptions.ControllerTimeoutError
            Raised if the fsadmin environment could not be created within its
            creation timeout.
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        self._logger.info("Fsadmin environment requested")
        timeout = Timeout("Filesystem admin creation", FSADMIN_TIMEOUT)
        state = self._state
        async with state.lock:
            if state.running:
                return
            try:
                state.in_progress = True
                state.last_modified = datetime.now(tz=UTC)
                async with timeout.enforce():
                    await self._create_fsadmin(timeout)
            except Exception as e:
                self._logger.exception("fsadmin creation failed")
                await self._maybe_post_slack_exception(e)
                self._logger.info("Cleaning up orphaned file server objects")
                await self._delete_fsadmin()
                raise
            else:
                state.running = True
            finally:
                state.in_progress = False
                state.last_modified = datetime.now(tz=UTC)

    async def delete(self) -> None:
        """Delete the fsadmin environment.

        Parameters
        ----------
        username
            Username of user.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        state = self._state
        async with state.lock:
            if not state.running:
                msg = "fsadmin not running"
                raise RuntimeError(msg)
            state.in_progress = True
            state.last_modified = datetime.now(tz=UTC)
            try:
                await self._delete_fsadmin()
                state.running = False
            finally:
                state.in_progress = False
                state.last_modified = datetime.now(tz=UTC)

    def get_status(self, username: str) -> FileserverStatus:
        """Get the status of a user's file server.

        Returns
        -------
        FileserverStatus
            Status of the user's file server.
        """
        if username not in self._servers:
            return FileserverStatus(running=False)
        return FileserverStatus(running=self._servers[username].running)

    async def list(self) -> list[str]:
        """List users with running file servers."""
        return [u for u, s in self._servers.items() if s.running]

    async def reconcile(self) -> None:
        """Reconcile internal state with Kubernetes.

        Runs at Nublado controller startup to reconcile internal state with
        the content of Kubernetes. This picks up changes made in Kubernetes
        outside of the controller, and is also responsible for building the
        internal state from the current state of Kubernetes during startup.
        It is called during startup and from a background task.
        """
        self._logger.info("Reconciling file server state")
        namespace = self._config.namespace
        timeout = Timeout(
            "Reading file server state", KUBERNETES_REQUEST_TIMEOUT
        )
        start = datetime.now(tz=UTC)
        seen = await self._storage.read_fileserver_state(namespace, timeout)
        known_users = {k for k, v in self._servers.items() if v.running}

        # Check each fileserver we found to see if it's properly running. If
        # it is and we didn't know about it, add it to our internal state and
        # assume it's supposed to be running. (This is the normal case for
        # reconcile during process startup.) If the file server isn't valid,
        # queue it up for removal.
        to_delete = set()
        unexpected = set()
        for username, state in seen.items():
            if self._builder.is_valid(username, state):
                if username not in known_users:
                    self._servers[username] = _State(running=True)
            elif username in self._servers:
                to_delete.add(username)
            else:
                unexpected.add(username)

        # Delete running file servers that are invalid in some way.
        await self._delete_invalid_servers(to_delete, start)

        # Delete invalid file servers that we weren't expecting to be running.
        await self._delete_unexpected_servers(unexpected, start)

        # Delete any file servers we were expecting to be running but for
        # which we didn't see a Kubernetes Job at all. This cleans up any
        # stray resources that might be left over, such as the ingress. This
        # should only be possible if something outside the controller deleted
        # resources.
        seen_users = {u for u in seen if u not in to_delete}
        await self._delete_missing_servers(known_users - seen_users, start)

        # Log completion.
        self._logger.debug("File server reconciliation complete")

    async def _delete_invalid_servers(
        self, to_delete: set[str], start: datetime
    ) -> None:
        """Delete running but invalid servers.

        Parameters
        ----------
        to_delete
            Usernames for servers to delete.
        start
            Start of the reconcile. Servers modified since then will be left
            alone.
        """
        for username in to_delete:
            if username in self._servers:
                if self._servers[username].modified_since(start):
                    continue
            msg = "Removing broken fileserver for user"
            self._logger.warning(msg, user=username)
            with contextlib.suppress(UnknownUserError):
                await self.delete(username)

    async def _delete_missing_servers(
        self, to_delete: set[str], start: datetime
    ) -> None:
        """Clean up resources for servers that have no ``Job``.

        Parameters
        ----------
        to_delete
            Usernames for servers to delete.
        start
            Start of the reconcile. Servers modified since then will be left
            alone.
        """
        for username in to_delete:
            if username in self._servers:
                if self._servers[username].modified_since(start):
                    continue
            msg = "No file server job for user, removing remnants"
            self._logger.warning(msg, user=username)
            with contextlib.suppress(UnknownUserError):
                await self.delete(username)

    async def _delete_unexpected_servers(
        self, to_delete: set[str], start: datetime
    ) -> None:
        """Delete invalid servers that weren't expected to be running.

        This is not necessarily an error case, since it can happen during
        startup if the controller didn't finish creating a server before it
        was shut down.

        Parameters
        ----------
        to_delete
            Usernames for servers to delete.
        start
            Start of the reconcile. Servers modified since then will be left
            alone.
        """
        for username in to_delete:
            if username in self._servers:
                continue
            msg = "File server present but not valid or wanted, deleting"
            self._logger.info(msg, user=username)

            # There is an unavoidable race condition where if the user for
            # this invalid file server attempts to create a valid file server
            # just as we make this call, we may delete parts of their new file
            # server. Solving this is complicated; live with it for now.
            name = self._builder.build_name(username)
            timeout = Timeout(
                "Deleting file server", KUBERNETES_REQUEST_TIMEOUT, username
            )
            await self._storage.delete(
                name, self._config.namespace, username, timeout
            )

    async def watch_servers(self) -> None:
        """Watch the file server namespace for completed file servers.

        Each file server has a timeout, after which it exits. When one exits,
        we want to clean up its Kubernetes objects and update its state. This
        method runs as a background task watching for changes and triggers the
        delete when appropriate.
        """
        namespace = self._config.namespace
        while True:
            try:
                async for change in self._storage.watch_pods(namespace):
                    if change.phase in (PodPhase.FAILED, PodPhase.SUCCEEDED):
                        pod = change.pod
                        username = self._builder.get_username_for_pod(pod)
                        if not username:
                            continue
                        self._logger.info(
                            "File server exited, cleaning up",
                            phase=change.phase.value,
                            user=username,
                        )
                        with contextlib.suppress(UnknownUserError):
                            await self.delete(username)
            except Exception as e:
                self._logger.exception("Error watching file server pod phase")
                await self._maybe_post_slack_exception(e)
                await asyncio.sleep(1)

    async def _create_file_server(
        self, user: GafaelfawrUserInfo, timeout: Timeout
    ) -> None:
        """Create a fileserver for the given user.

        Waits for the file server to be operational. Should be called with
        the user's lock held.

        Parameters
        ----------
        user
            User for which to create a file server.
        timeout
            How long to wait for the file server to start.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        fileserver = self._builder.build(user)
        self._logger.info("Creating new file server", user=user.username)
        await self._storage.create(self._config.namespace, fileserver, timeout)

    async def _delete_fsadmin(self) -> None:
        """Delete any fsadmin for the given user.

        Should be called with the lock held.

        Raises
        ------
        ControllerTimeoutError
            Raised if deletion of the file server timed out.
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        name = FSADMIN_POD_NAME
        namespace = FSADMIN_NAMESPACE
        timeout = Timeout("File server deletion", FSADMIN_TIMEOUT)
        try:
            async with timeout.enforce():
                await self._storage.delete(name, namespace, timeout)
        except Exception as e:
            msg = "Error deleting file server"
            self._logger.exception(msg)
            await self._maybe_post_slack_exception(e)
            raise

    async def _maybe_post_slack_exception(
        self, exc: Exception, username: str | None = None
    ) -> None:
        """Post an exception to Slack if Slack reporting is configured.

        Parameters
        ----------
        exc
            Exception to report.
        username
            Username that triggered the exception, if known.
        """
        if not self._slack:
            return
        if isinstance(exc, SlackException):
            if username:
                exc.user = username
            await self._slack.post_exception(exc)
        else:
            await self._slack.post_uncaught_exception(exc)
