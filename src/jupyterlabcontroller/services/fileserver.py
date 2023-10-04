"""Service to manage user fileservers."""


from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import timedelta

from structlog.stdlib import BoundLogger

from ..config import FileserverConfig
from ..exceptions import DisabledError, MissingObjectError
from ..models.domain.fileserver import FileserverUserMap
from ..models.v1.lab import UserInfo
from ..storage.k8s import K8sStorageClient
from ..storage.kubernetes.fileserver import FileserverStorage
from .builder.fileserver import FileserverBuilder


class FileserverStateManager:
    def __init__(
        self,
        *,
        config: FileserverConfig,
        fileserver_builder: FileserverBuilder,
        fileserver_storage: FileserverStorage,
        k8s_client: K8sStorageClient,
        logger: BoundLogger,
    ) -> None:
        """The FileserverStateManager is a process-wide singleton."""
        self._config = config
        self._builder = fileserver_builder
        self._storage = fileserver_storage
        self._k8s_client = k8s_client
        self._logger = logger

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
        if not (
            await self._user_map.get(username)
            and await self._k8s_client.check_fileserver_present(
                username, self._config.namespace
            )
        ):
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
        fileserver = self._builder.build_fileserver(user)
        timeout = timedelta(seconds=self._config.creation_timeout)
        async with self._lock[username]:
            self._logger.info(f"Creating new fileserver for {username}")
            await self._storage.create(namespace, fileserver, timeout)
            task = asyncio.create_task(self._discard_when_done(username))
            self._watches.add(task)
            task.add_done_callback(self._watches.discard)
            await self._user_map.set(username)

    async def delete(self, username: str) -> None:
        if not self._started:
            raise DisabledError("Fileserver is not started.")
        name = self._builder.build_fileserver_name(username)
        async with self._lock[username]:
            await self._user_map.remove(username)
            await self._storage.delete(name, self._config.namespace)

    async def list(self) -> list[str]:
        return await self._user_map.list()

    async def start(self) -> None:
        if not self._config.enabled:
            raise DisabledError("Fileserver is disabled in configuration")
        if not await self._k8s_client.check_namespace(self._config.namespace):
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
        name = self._builder.build_fileserver_name(username)
        await self._storage.wait_for_pod_exit(name, self._config.namespace)
        await self.delete(username)

    async def _reconcile_user_map(self) -> None:
        """Reconcile internal state with Kubernetes.

        We need to run this on startup, to synchronize the user map resource
        with observed state.
        """
        self._logger.debug("Reconciling fileserver user map")
        mapped_users = set(await self.list())
        observed_map = await self._k8s_client.get_observed_fileserver_state(
            self._config.namespace
        )
        # Tidy up any no-longer-running users.  They aren't running, but they
        # might have some objects remaining.
        observed_users = set(observed_map.keys())
        missing_users = mapped_users - observed_users
        if missing_users:
            self._logger.info(
                f"Users {missing_users} have broken fileservers; removing."
            )
        for user in missing_users:
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
        self._logger.debug("Filserver user map reconciliation complete")
        self._logger.debug(f"Users with fileservers: {observed_users}")
