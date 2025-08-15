"""Service to manage administrative filesystem environment."""

# This all looks extremely similar to the fileserver service, and
# that's no accident.  The fsadmin environment is essentially a
# fileserver with all the guardrails taken off, running in its own
# namespace (but for obvious reasons, lacking a WebDAV interface).
#
# There's probably room for some consolidation and inheritance here,
# but fsadmin lacks the concept of a username, so we'd have to be
# careful about method signatures, since most of the fileserver
# methods want a username as a parameter.

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from safir.slack.blockkit import SlackException
from safir.slack.webhook import SlackWebhookClient
from structlog.stdlib import BoundLogger

from ..config import FSAdminConfig
from ..constants import KUBERNETES_REQUEST_TIMEOUT
from ..models.domain.kubernetes import PodPhase
from ..storage.kubernetes.fsadmin import FSAdminStorage
from ..timeout import Timeout
from ._state import ServiceState
from .builder.fsadmin import FSAdminBuilder

__all__ = ["FSAdminManager"]


class FSAdminManager:
    """Manage filesystem admin environment.

    This class is a process-wide singleton that manages the fsadmin
    environment.

    Parameters
    ----------
    config
        Configuration for fsadmin environment.
    volumes
        Configuration for volumes to mount.
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
        config: FSAdminConfig,
        fsadmin_builder: FSAdminBuilder,
        fsadmin_storage: FSAdminStorage,
        slack_client: SlackWebhookClient | None,
        logger: BoundLogger,
    ) -> None:
        self._config = config
        self._builder = fsadmin_builder
        self._storage = fsadmin_storage
        self._slack = slack_client
        self._logger = logger
        self._state = ServiceState(running=False)

    async def create(self) -> None:
        """Ensure the fsadmin environment exists.

        If we don't have a filesystem admin environment, create it.  If we do,
        just return. This gets called by the handler when someone POSTs to the
        ``/fsadmin/v1/service`` ingress.

        Raises
        ------
        controller.exceptions.ControllerTimeoutError
            Raised if the fsadmin environment could not be created within its
            creation timeout.
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        self._logger.info("Fsadmin environment requested")
        timeout = Timeout("Filesystem admin creation", self._config.timeout)
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
                self._logger.info("Cleaning up orphaned fsadmin objects")
                await self._delete_fsadmin()
                raise
            else:
                state.running = True
            finally:
                state.in_progress = False
                state.last_modified = datetime.now(tz=UTC)

    async def delete(self) -> None:
        """Delete the fsadmin environment.  This gets called by the handler
        when someone sends a DELETE to the ``/fsadmin/v1/service`` ingress.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        state = self._state
        async with state.lock:
            state.in_progress = True
            state.last_modified = datetime.now(tz=UTC)
            try:
                await self._delete_fsadmin()
                state.running = False
            finally:
                state.in_progress = False
                state.last_modified = datetime.now(tz=UTC)

    async def is_ready(self) -> bool:
        """Get the ready status of the fsadmin container.  This gets called
        by the handler when someone issues a GET against the
        ``/fsadmin/v1/service`` ingress.

        Returns
        -------
        bool
            True if the fsadmin container is ready.
        """
        timeout = Timeout("Reading fsadmin state", KUBERNETES_REQUEST_TIMEOUT)
        retval = False
        state = self._state
        async with state.lock:
            state.in_progress = True
            try:
                retval = await self._storage.is_fsadmin_ready(timeout)
            finally:
                state.in_progress = False
        return retval

    async def reconcile(self) -> None:
        """Reconcile internal state with Kubernetes.

        Runs at Nublado controller startup to reconcile internal state with
        the content of Kubernetes. This picks up changes made in Kubernetes
        outside of the controller, and is also responsible for building the
        internal state from the current state of Kubernetes during startup.
        It is called during startup and from a background task.
        """
        self._logger.info("Reconciling fsadmin state")
        timeout = Timeout("Reading fsadmin state", KUBERNETES_REQUEST_TIMEOUT)
        async with self._state.lock:
            ready = await self._storage.is_fsadmin_ready(timeout)
            if not ready:
                # Deleting a nonexistent fsadmin namespace is OK.
                # If it's totally not-present, this is a no-op.  If some
                # bits are there but the fsadmin instance is not healthy,
                # it will delete them.
                await self._storage.delete(timeout)
            else:
                self._state.running = True

        # Log completion.
        self._logger.debug("Reconciliation complete for fsadmin")

    async def watch_servers(self) -> None:
        """Watch the fsadmin namespace for completed fsadmin pods.

        If fsadmin exits, we want to clean up its Kubernetes objects
        and update its state. This method runs as a background task
        watching for changes and triggers the delete when appropriate.
        """
        while True:
            try:
                async for change in self._storage.watch_pod():
                    if change.phase in (PodPhase.FAILED, PodPhase.SUCCEEDED):
                        self._logger.info(
                            "fsadmin pod exited, cleaning up",
                            phase=change.phase.value,
                        )
                        await self.delete()
            except Exception as e:
                self._logger.exception("Error watching fsadmin pod phase")
                await self._maybe_post_slack_exception(e)
                await asyncio.sleep(1)

    async def _create_fsadmin(self, timeout: Timeout) -> None:
        """Create fsadmin namespace and contents.

        Should be called with the lock held.

        Raises
        ------
        ControllerTimeoutError
            Raised if creation of the file server timed out.
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        fsadmin = self._builder.build()
        await self._storage.create(fsadmin, timeout)

    async def _delete_fsadmin(self) -> None:
        """Delete fsadmin namespace (and contents).

        Should be called with the lock held.

        Raises
        ------
        ControllerTimeoutError
            Raised if deletion of the file server timed out.
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        timeout = Timeout("File server deletion", self._config.timeout)
        try:
            async with timeout.enforce():
                await self._storage.delete(timeout)
        except Exception as e:
            msg = "Error deleting file server"
            self._logger.exception(msg)
            await self._maybe_post_slack_exception(e)
            raise

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
            await self._slack.post_exception(exc)
        else:
            await self._slack.post_uncaught_exception(exc)
