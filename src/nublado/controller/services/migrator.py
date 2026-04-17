"""Service to manage migrator environment."""

import asyncio

from safir.slack.webhook import SlackWebhookClient
from structlog.stdlib import BoundLogger

from ..config import Config
from ..models.v1.migrator import MigratorStatus
from ..storage.kubernetes.migrator import MigratorStorage
from ..timeout import Timeout
from .builder.lab import LabBuilder
from .builder.migrator import MigratorBuilder

__all__ = ["MigratorManager"]


class MigratorManager:
    """Manage filesystem migrator.

    This singleton manages the migrator environment and maintains a cache
    for particular user migrations.

    Parameters
    ----------
    config
        Nublado configuration (used for home volume and timeout).
    lab_builder
        Lab builder (used for home volume).
    migrator_storage
        Shared storage driver for migrator K8s objects.
    slack_client
        Optional Slack webhook client for alerts.
    logger
        Logger to use.
    """

    def __init__(
        self,
        *,
        config: Config,
        lab_builder: LabBuilder,
        migrator_storage: MigratorStorage,
        slack_client: SlackWebhookClient | None,
        logger: BoundLogger,
    ) -> None:
        self._lab_config = config.lab
        self._fsadmin_config = config.fsadmin
        self._timeout = self._fsadmin_config.timeout
        self._builder = MigratorBuilder(
            config=config, lab_builder=lab_builder, logger=logger
        )
        self._storage = migrator_storage
        self._slack = slack_client
        self._logger = logger
        self._lock = asyncio.Lock()

    async def create(self, old_user: str, new_user: str) -> MigratorStatus:
        """Ensure the migrator environment exists.

        If we don't have a migration environment for this user pair,
        create it.  If we do, just return. This gets called by the
        handler when someone POSTs to the ``/migrator/v1/service``
        ingress.

        Return
        ------
        MigratorStatus
            Status for the created pod.

        Raises
        ------
        controller.exceptions.ControllerTimeoutError
            Raised if the migrator environment could not be created within its
            creation timeout.
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        self._logger.info(f"Migrator for {old_user} -> {new_user} requested")
        timeout = Timeout("Migrator creation", self._timeout)
        objs = self._builder.build(old_user, new_user)
        async with self._lock:
            status = await self._storage.create(
                old_user, new_user, objs, timeout
            )
            status.raise_for_status()
            return status

    async def get_status(
        self, old_user: str, new_user: str
    ) -> MigratorStatus | None:
        """Return the status for the migrator container for a particular
        user pair, or None if no migration has been attempted.

        Raises
        ------
        controller.exceptions.ControllerTimeoutError
            Raised if the fsadmin environment could not be queried within its
            query timeout.
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        self._logger.info(
            f"Requesting migrator status for {old_user} -> {new_user}"
        )
        timeout = Timeout("Migration query", self._timeout)
        objs = self._builder.build(old_user, new_user)
        async with self._lock:
            return await self._storage.get_status(
                old_user, new_user, objs, timeout
            )
