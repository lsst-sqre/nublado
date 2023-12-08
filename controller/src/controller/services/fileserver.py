"""Service to manage user fileservers."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field

from safir.slack.blockkit import SlackException
from safir.slack.webhook import SlackWebhookClient
from structlog.stdlib import BoundLogger

from ..config import EnabledFileserverConfig
from ..constants import (
    KUBERNETES_REQUEST_TIMEOUT,
)
from ..exceptions import (
    UnknownUserError,
)
from ..models.domain.gafaelfawr import GafaelfawrUserInfo
from ..models.domain.kubernetes import PodPhase
from ..storage.kubernetes.fileserver import FileserverStorage
from ..timeout import Timeout
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
    fileserver_builder
        Builder that constructs file server Kubernetes objects.
    fileserver_storage
        Kubernetes storage layer for file servers.
    slack_client
        Optional Slack webhook client for alerts.
    logger
        Logger to use.
    """

    def __init__(
        self,
        *,
        config: EnabledFileserverConfig,
        fileserver_builder: FileserverBuilder,
        fileserver_storage: FileserverStorage,
        slack_client: SlackWebhookClient | None,
        logger: BoundLogger,
    ) -> None:
        self._config = config
        self._builder = fileserver_builder
        self._storage = fileserver_storage
        self._slack = slack_client
        self._logger = logger

        # Mapping of usernames to internal state.
        self._servers: dict[str, _State] = {}

    async def create(self, user: GafaelfawrUserInfo) -> None:
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
        controller.exceptions.ControllerTimeoutError
            Raised if the file server could not be created within its creation
            timeout.
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        logger = self._logger.bind(user=user.username)
        logger.info("File server requested")
        if user.username not in self._servers:
            self._servers[user.username] = _State(running=False)
        state = self._servers[user.username]
        timeout = Timeout(
            "File server creation",
            self._config.creation_timeout,
            user.username,
        )
        async with state.lock:
            if state.running:
                return
            try:
                async with timeout.enforce():
                    await self._create_file_server(user, timeout)
            except Exception as e:
                logger.exception("File server creation failed")
                await self._maybe_post_slack_exception(e, user.username)
                logger.info("Cleaning up orphaned file server objects")
                await self._delete_file_server(user.username)
                raise
            else:
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
        seen = await self._storage.read_fileserver_state(namespace, timeout)
        known_users = {k for k, v in self._servers.items() if v.running}

        # Check each fileserver we found to see if it's properly running. If
        # not, delete it and remove it from the seen map.
        to_delete = set()
        invalid = set()
        for username, state in seen.items():
            valid = self._builder.is_valid(username, state)
            if valid:
                self._servers[username] = _State(running=valid)
            elif username in self._servers:
                to_delete.add(username)
            else:
                invalid.add(username)
        seen = {k: v for k, v in seen.items() if k not in to_delete}

        # Also tidy up any supposedly-running users that we didn't find. They
        # may have some objects remaining. This should only be possible if
        # something outside of the controller deleted resources.
        seen_users = set(seen.keys())
        for user in (known_users - seen_users) | to_delete:
            msg = "Removing broken fileserver for user"
            self._logger.warning(msg, user=user)
            await self.delete(user)
        for username in invalid:
            if username in self._servers:
                continue
            msg = "File server present but not running, deleteing"
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
        self._logger.debug("File server reconciliation complete")

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

    async def _delete_file_server(self, username: str) -> None:
        """Delete any file server objects for the given user.

        Should be called with the user's lock held.

        Parameters
        ----------
        username
            Username of user.

        Raises
        ------
        ControllerTimeoutError
            Raised if deletion of the file server timed out.
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        name = self._builder.build_name(username)
        namespace = self._config.namespace
        timeout = Timeout(
            "File server deletion", self._config.delete_timeout, username
        )
        try:
            async with timeout.enforce():
                await self._storage.delete(name, namespace, username, timeout)
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
