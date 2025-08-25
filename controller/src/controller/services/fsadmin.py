"""Service to manage administrative filesystem environment."""

from __future__ import annotations

import asyncio
import datetime

from safir.slack.blockkit import SlackException
from safir.slack.webhook import SlackWebhookClient
from structlog.stdlib import BoundLogger

from ..config import FSAdminConfig
from ..storage.kubernetes.fsadmin import FSAdminStorage
from ..timeout import Timeout
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
        self._lock = asyncio.Lock()

    async def create(self) -> datetime.datetime:
        """Ensure the fsadmin environment exists.

        If we don't have a filesystem admin environment, create it.  If we do,
        just return. This gets called by the handler when someone POSTs to the
        ``/fsadmin/v1/service`` ingress.

        Return
        ------
        datetime.datetime
            Time at which pod went into ``Running`` phase.

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
        try:
            async with self._lock:
                if start_time := await self._storage.get_start_time(timeout):
                    return start_time
                fsadmin = self._builder.build()
                # Delete should be almost-instant if the objects do not exist.
                # If they do, then the pod isn't working and they need
                # to be destroyed and recreated.
                await self._storage.delete(fsadmin, timeout)
                return await self._storage.create(fsadmin, timeout)
        except Exception as e:
            msg = "Error creating fsadmin"
            self._logger.exception(msg)
            await self._maybe_post_slack_exception(e)
            raise

    async def delete(self) -> None:
        """Delete the fsadmin environment.  This gets called by the handler
        when someone sends a DELETE to the ``/fsadmin/v1/service`` ingress.

        Raises
        ------
        controller.exceptions.ControllerTimeoutError
            Raised if the fsadmin environment could not be created within its
            creation timeout.
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        timeout = Timeout("Filesystem admin creation", self._config.timeout)
        try:
            async with self._lock:
                fsadmin = self._builder.build()
                await self._storage.delete(fsadmin, timeout)
        except Exception as e:
            msg = "Error deleting fsadmin"
            self._logger.exception(msg)
            await self._maybe_post_slack_exception(e)
            raise

    async def get_start_time(self) -> datetime.datetime | None:
        """Get the start time from the fsadmin container.  This gets called
        by the handler when someone issues a GET against the
        ``/fsadmin/v1/service`` ingress.

        Returns
        -------
        datetime.datetime | None
            Returns container's start time if the fsadmin container is ready.
            If not, returns ``None``.
        """
        timeout = Timeout("Filesystem admin query", self._config.timeout)
        try:
            async with self._lock:
                return await self._storage.get_start_time(timeout)
        except Exception as e:
            msg = "Error querying fsadmin status"
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
