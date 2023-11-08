"""Service to manage user fileservers."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from datetime import timedelta

from aiojobs import Scheduler
from safir.datetime import current_datetime
from safir.slack.blockkit import SlackException
from safir.slack.webhook import SlackWebhookClient
from structlog.stdlib import BoundLogger

from ..config import FileserverConfig
from ..constants import FILE_SERVER_REFRESH_INTERVAL
from ..exceptions import (
    MissingObjectError,
    NotConfiguredError,
    UnknownUserError,
)
from ..models.domain.kubernetes import PodPhase
from ..models.v1.lab import UserInfo
from ..storage.kubernetes.fileserver import FileserverStorage
from .builder.fileserver import FileserverBuilder

__all__ = ["FileserverManager"]


@dataclass
class _State:
    """State of the file server for a given user."""

    running: bool
    """Whether the file server is running."""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    """Lock to prevent two operations from happening at once."""


class FileserverManager:
    """Manage user file servers.

    Unlike with labs, file servers are not normally explicitly shut down.
    Instead, the file server has an internal idle timeout and exits once that
    has expired with no activity. A background task watches for exited file
    servers, deletes the associated resources, and updates the internal state.

    This class is a process-wide singleton that manages that background task
    and the user file server state.

    Parameters
    ----------
    config
        Configuration for file servers. File servers are guaranteed to be
        enabled by `~controller.factory.ProcessContext`.
    base_url
        Base URL for this Phalanx installation, used in the template presented
        to the user after a file server has been created.
    fileserver_builder
        Builder that constructs file server Kubernetes objects.
    fileserver_storage
        Kubernetes storage layer for file servers.
    logger
        Logger to use.
    """

    def __init__(
        self,
        *,
        config: FileserverConfig,
        base_url: str,
        fileserver_builder: FileserverBuilder,
        fileserver_storage: FileserverStorage,
        slack_client: SlackWebhookClient | None,
        logger: BoundLogger,
    ) -> None:
        self._config = config
        self._base_url = base_url
        self._builder = fileserver_builder
        self._storage = fileserver_storage
        self._slack = slack_client
        self._logger = logger

        if not self._config.enabled:
            raise NotConfiguredError("Fileserver is disabled in configuration")

        # Background task management.
        self._scheduler: Scheduler | None = None

        # Mapping of usernames to internal state.
        self._servers: dict[str, _State] = {}

    async def create(self, user: UserInfo) -> None:
        """Ensure a file server exists for the given user.

        If the user doesn't have a fileserver, create it.  If the user already
        has a fileserver, just return. This gets called by the handler when a
        user comes in through the ``/files`` ingress.

        Parameters
        ----------
        user
            User for which to create a file server.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        TimeoutError
            Raised if the file server could not be created within its creation
            timeout.
        """
        logger = self._logger.bind(user=user.username)
        logger.info("File server requested")
        if user.username not in self._servers:
            self._servers[user.username] = _State(running=False)
        state = self._servers[user.username]
        timeout = self._config.creation_timeout
        start = current_datetime(microseconds=True)
        async with state.lock:
            if state.running:
                return
            try:
                async with asyncio.timeout(timeout.total_seconds()):
                    await self._create_file_server(user, timeout)
            except TimeoutError as e:
                now = current_datetime(microseconds=True)
                elapsed = (now - start).total_seconds()
                msg = f"File server creation timed out after {elapsed}s"
                logger.exception(msg)
                logger.info("Cleaning up orphaned file server objects")
                await self._delete_file_server(user.username)
                raise TimeoutError(msg) from e
            except Exception as e:
                logger.exception("File server creation failed")
                await self._maybe_post_slack_exception(e, user.username)
                logger.info("Cleaning up orphaned file server objects")
                await self._delete_file_server(user.username)
                raise
            state.running = True

    async def delete(self, username: str) -> None:
        """Delete the file server for a user.

        Parameters
        ----------
        username
            Username of user.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        if username not in self._servers:
            raise UnknownUserError(f"Unknown user {username}")
        state = self._servers[username]
        async with state.lock:
            if not state.running:
                msg = f"File server for {username} not running"
                raise UnknownUserError(msg)
            await self._delete_file_server(username)
            state.running = False

    async def list(self) -> list[str]:
        """List users with running file servers."""
        return [u for u, s in self._servers.items() if s.running]

    async def start(self) -> None:
        """Start the background file server tasks.

        Reconstructs the user state map in the foreground before backgrounding
        the reconciliation and monitor tasks.
        """
        namespace = self._config.namespace
        if not await self._storage.namespace_exists(namespace):
            raise MissingObjectError(
                "File server namespace missing",
                kind="Namespace",
                name=namespace,
            )
        await self._reconcile_file_servers()
        self._scheduler = Scheduler()
        self._logger.info("Starting file server watcher task")
        await self._scheduler.spawn(self._watch_file_servers())
        self._logger.info("Starting file server periodic reconciliation task")
        await self._scheduler.spawn(self._reconcile_loop())

    async def stop(self) -> None:
        """Stop background file server tasks.

        Any started file servers will keep running.
        """
        if not self._scheduler:
            msg = "File server background tasks were already stopped"
            self._logger.warning(msg)
            return
        self._logger.info("Stopping file server background tasks")
        await self._scheduler.close()
        self._scheduler = None

    async def _create_file_server(
        self, user: UserInfo, timeout: timedelta
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

    async def _delete_file_server(self, username: str) -> None:
        """Delete any file server objects for the given user.

        Should be called with the user's lock held.

        Parameters
        ----------
        username
            Username of user.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        TimeoutError
            Raised if deletion of the file server timed out.
        """
        name = self._builder.build_name(username)
        start = current_datetime(microseconds=True)
        try:
            await self._storage.delete(name, self._config.namespace)
        except TimeoutError as e:
            now = current_datetime(microseconds=True)
            elapsed = (now - start).total_seconds()
            msg = f"File server deletion timed out after {elapsed}s"
            self._logger.exception(msg, user=username)
            raise TimeoutError(msg) from e
        except Exception as e:
            msg = "Error deleting file server"
            self._logger.exception(msg, user=username)
            await self._maybe_post_slack_exception(e, username)
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

    async def _reconcile_file_servers(self) -> None:
        """Reconcile internal state with Kubernetes.

        Runs at Nublado controller startup to reconcile the initially empty
        state map with the contents of Kubernetes.
        """
        self._logger.debug("Reconciling file server state")
        namespace = self._config.namespace
        observed = await self._storage.read_fileserver_state(namespace)
        mapped_users = set(self._servers.keys())

        # Check each fileserver we found to see if it's properly running. If
        # not, delete it and remove it from the observed map.
        to_delete = set()
        for username, state in observed.items():
            valid = self._builder.is_valid(username, state)
            if username not in self._servers:
                self._servers[username] = _State(running=valid)
            if not valid:
                msg = "File server present but not running, deleteing"
                self._logger.info(msg, user=username)
                to_delete.add(username)
        observed = {k: v for k, v in observed.items() if k not in to_delete}
        for username in to_delete:
            name = self._builder.build_name(username)
            await self._storage.delete(name, self._config.namespace)

        # Tidy up any no-longer-running users. They aren't running, but they
        # might have some objects remaining. This should only be possible if
        # something outside of the controller deleted resources.
        observed_users = set(observed.keys())
        for user in mapped_users - observed_users:
            msg = "Removing broken fileserver for user"
            self._logger.warning(msg, user=user)
            await self.delete(user)
        self._logger.debug("File server reconciliation complete")

    async def _reconcile_loop(self) -> None:
        """Run in the background by `start`, stopped with `stop`."""
        while True:
            start = current_datetime(microseconds=True)
            try:
                await self._reconcile_file_servers()
            except Exception as e:
                self._logger.exception("Unable to reconcile file servers")
                await self._maybe_post_slack_exception(e)
            now = current_datetime(microseconds=True)
            delay = FILE_SERVER_REFRESH_INTERVAL - (now - start)
            if delay.total_seconds() < 1:
                msg = "File server reconciliation is running continuously"
                self._logger.warning(msg)
            else:
                await asyncio.sleep(delay.total_seconds())

    async def _watch_file_servers(self) -> None:
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
