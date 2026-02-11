"""Service to manage administrative filesystem environment."""

from __future__ import annotations

import asyncio

from safir.slack.webhook import SlackWebhookClient
from structlog.stdlib import BoundLogger

from ..config import FSAdminConfig
from ..exceptions import InvalidPodPhaseError, PodNotFoundError
from ..models.v1.fsadmin import FSAdminStatus
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

    async def create(self) -> FSAdminStatus:
        """Ensure the fsadmin environment exists.

        If we don't have a filesystem admin environment, create it.  If we do,
        just return. This gets called by the handler when someone POSTs to the
        ``/fsadmin/v1/service`` ingress.

        Return
        ------
        FSAdminStatus
            Status for the created pod.

        Raises
        ------
        controller.exceptions.ControllerTimeoutError
            Raised if the fsadmin environment could not be created within its
            creation timeout.
        InvalidPodPhaseError
            Pod is not in ``Running`` phase.
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        PodNotFoundError
            Pod does not exist.
        """
        self._logger.info("Fsadmin environment requested")
        timeout = Timeout("Filesystem admin creation", self._config.timeout)
        async with self._lock:
            try:
                return await self._storage.get_status(timeout)
            except PodNotFoundError, InvalidPodPhaseError:
                # It's not both there and healthy, so (re)create it.
                fsadmin = self._builder.build()
                return await self._storage.create(fsadmin, timeout)

    async def delete(self) -> None:
        """Delete the fsadmin environment.  This gets called by the handler
        when someone sends a DELETE to the ``/fsadmin/v1/service`` ingress.

        Raises
        ------
        controller.exceptions.ControllerTimeoutError
            Raised if the fsadmin environment could not be deleted within its
            creation timeout.
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        timeout = Timeout("Filesystem admin deletion", self._config.timeout)
        async with self._lock:
            fsadmin = self._builder.build()
            await self._storage.delete(fsadmin, timeout)

    async def get_status(self) -> FSAdminStatus:
        """Return the status for the fsadmin container, if it exists and is
        healthy.  If it does not exist, or is not ready to accept work,
        raise an exception.

        This gets called by the handler when someone issues a GET against
        the ``/fsadmin/v1/service`` ingress.

        Raises
        ------
        controller.exceptions.ControllerTimeoutError
            Raised if the fsadmin environment could not be queried within its
            query timeout.
        InvalidPodPhaseError
            Pod is not in ``Running`` phase.
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        PodNotFoundError
            Pod does not exist.
        """
        timeout = Timeout("Filesystem admin query", self._config.timeout)
        async with self._lock:
            return await self._storage.get_status(timeout)
