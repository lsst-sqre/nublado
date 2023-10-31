"""Service to manage user fileservers."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import timedelta

from structlog.stdlib import BoundLogger

from ..config import FileserverConfig
from ..exceptions import MissingObjectError, NotConfiguredError
from ..models.domain.fileserver import FileserverUserMap
from ..models.v1.lab import UserInfo
from ..storage.kubernetes.fileserver import FileserverStorage
from .builder.fileserver import FileserverBuilder


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
        enabled by `~jupyterlabcontroller.factory.ProcessContext`.
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
        fileserver_builder: FileserverBuilder,
        fileserver_storage: FileserverStorage,
        logger: BoundLogger,
    ) -> None:
        self._config = config
        self._builder = fileserver_builder
        self._storage = fileserver_storage
        self._logger = logger

        if not self._config.enabled:
            raise NotConfiguredError("Fileserver is disabled in configuration")

        self._user_map = FileserverUserMap()
        self._tasks: set[asyncio.Task] = set()
        self._started = False

        # This maps usernames to locks, so we have a lock per user, and if
        # there is no lock for that user, requesting one gets you a new lock.
        self._lock: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

        # Maps users to the tasks watching for their pods to exit
        self._watches: set[asyncio.Task] = set()

    async def create(self, user: UserInfo) -> None:
        """If the user doesn't have a fileserver, create it.  If the user
        already has a fileserver, just return.

        This gets called by the handler when a user comes in through the
        /files ingress.
        """
        username = user.username
        self._logger.info(f"Fileserver requested for {username}")
        if not await self._user_map.get(username):
            try:
                await self._create_fileserver(user)
            except Exception:
                msg = (
                    f"Fileserver creation for {username} failed, deleting"
                    " fileserver objects"
                )
                self._logger.exception(msg)
                await self.delete(username)
                raise

    async def _create_fileserver(self, user: UserInfo) -> None:
        """Create a fileserver for the given user.  Wait for it to be
        operational.  If we can't build it, raise an error.
        """
        username = user.username
        namespace = self._config.namespace
        fileserver = self._builder.build(user)
        timeout = timedelta(seconds=self._config.creation_timeout)
        async with self._lock[username]:
            self._logger.info(f"Creating new fileserver for {username}")
            await self._storage.create(namespace, fileserver, timeout)
            task = asyncio.create_task(self._discard_when_done(username))
            self._watches.add(task)
            task.add_done_callback(self._watches.discard)
            await self._user_map.set(username)

    async def delete(self, username: str) -> None:
        name = self._builder.build_name(username)
        async with self._lock[username]:
            await self._user_map.remove(username)
            await self._storage.delete(name, self._config.namespace)

    async def list(self) -> list[str]:
        return await self._user_map.list()

    async def start(self) -> None:
        if not await self._storage.namespace_exists(self._config.namespace):
            raise MissingObjectError(
                "File server namespace missing",
                kind="Namespace",
                name=self._config.namespace,
            )
        await self._reconcile_user_map()
        self._started = True

    async def stop(self) -> None:
        # If you call this when it's already stopped or stopping it doesn't
        # care.
        #
        # We want to leave started fileservers running.  We will find them
        # again on our next restart, and user service will not be interrupted.
        #
        # No one can start a new server while self._started is False.
        self._started = False
        # Remove all pending fileserver watch tasks
        for task in self._watches:
            task.cancel()

    async def _discard_when_done(self, username: str) -> None:
        name = self._builder.build_name(username)
        await self._storage.wait_for_pod_exit(name, self._config.namespace)
        await self.delete(username)

    async def _reconcile_user_map(self) -> None:
        """Reconcile internal state with Kubernetes.

        Runs at Nublado controller startup to reconcile the initially empty
        state map with the contents of Kubernetes.
        """
        self._logger.debug("Reconciling fileserver user map")
        namespace = self._config.namespace
        mapped_users = set(await self.list())
        observed = await self._storage.read_fileserver_state(namespace)

        # Check each fileserver we found to see if it's properly running. If
        # not, delete it and remove it from the observed map.
        to_delete = set()
        for username, state in observed.items():
            valid = self._builder.is_valid(username, state)
            if not valid:
                msg = "File server present but not running, deleteing"
                self._logger.info(msg, user=username)
                await self.delete(username)
                to_delete.add(username)
        observed = {k: v for k, v in observed.items() if k not in to_delete}

        # Tidy up any no-longer-running users. They aren't running, but they
        # might have some objects remaining. Currently, this can only happen
        # if the fileserver is stopped and then started again. Normally, the
        # user map will start as empty.
        observed_users = set(observed.keys())
        for user in mapped_users - observed_users:
            msg = "Removing broken fileserver for user"
            self._logger.warning(msg, user=user)
            await self.delete(user)

        # We know any observed users are running, so we need to create tasks
        # to clean them up when they exit, and then mark them as set in the
        # user map.
        for user in observed_users:
            async with self._lock[user]:
                task = asyncio.create_task(self._discard_when_done(user))
                self._watches.add(task)
                task.add_done_callback(self._watches.discard)
                await self._user_map.set(user)
        self._logger.info("Fileserver user map reconciliation complete")
        self._logger.debug(f"Users with fileservers: {observed_users}")
