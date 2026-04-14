"""Service to manage migrator environment."""

import asyncio

from safir.slack.webhook import SlackWebhookClient
from structlog.stdlib import BoundLogger

from ..config import FSAdminConfig, LabConfig
from ..models.v1.migrator import MigratorStatus
from ..storage.kubernetes.migrator import MigratorStorage
from ..timeout import Timeout
from .builder.lab import LabBuilder
from .builder.migrator import MigratorBuilder

__all__ = ["MigratorManager"]


class MigratorManager:
    """Manage filesystem migrator.

    This class is a manages the migrator environment for a particular user
    migration.

    Parameters
    ----------
    old_user
        Username for source user to copy from.
    new_user
        Username for target user to copy to.
    lab_config
        Lab configuration (used for home volume).
    fsadmin_config
        Filesystem admin configuration (used for timeout)
    lab_builder
        Lab builder (used for home volume)
    slack_client
        Optional Slack webhook client for alerts.
    logger
        Logger to use.
    debug
        Whether to enable debug logging.
    """

    def __init__(
        self,
        *,
        old_user: str,
        new_user: str,
        lab_config: LabConfig,
        fsadmin_config: FSAdminConfig,
        lab_builder: LabBuilder,
        migrator_storage: MigratorStorage,
        slack_client: SlackWebhookClient | None,
        logger: BoundLogger,
        debug: bool = False,
    ) -> None:
        self._old_user = old_user
        self._new_user = new_user
        self._lab_config = lab_config
        self._fsadmin_config = fsadmin_config
        self._timeout = fsadmin_config.timeout
        self._builder = MigratorBuilder(
            old_user=old_user,
            new_user=new_user,
            lab_config=lab_config,
            fsadmin_config=fsadmin_config,
            lab_builder=lab_builder,
            logger=logger,
            debug=debug,
        )
        self._storage = migrator_storage
        self._slack = slack_client
        self._logger = logger
        self._debug = debug
        self._lock = asyncio.Lock()

    async def create(self) -> MigratorStatus:
        """Ensure the migrator environment exists.

        If we don't have a filesystem admin environment, create it.  If we do,
        just return. This gets called by the handler when someone POSTs to the
        ``/migrator/v1/service`` ingress.

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
        self._logger.info(
            f"Migrator for {self._old_user} -> {self._new_user}requested"
        )
        timeout = Timeout("Migrator creation", self._timeout)
        objs = self._builder.build()
        async with self._lock:
            return await self._storage.create(objs, timeout)

    async def get_status(self) -> MigratorStatus | None:
        """Return the status for the migrator container.  If the pod is not
        running, remove the exited pod, if it exists.

        Raises
        ------
        controller.exceptions.ControllerTimeoutError
            Raised if the fsadmin environment could not be queried within its
            query timeout.
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        self._logger.info(
            f"Requesting migrator status for {self._old_user}"
            f" -> {self._new_user}"
        )
        timeout = Timeout("Migration query", self._timeout)
        pod_name = self._builder.build_pod_name()
        objs = self._builder.build()
        async with self._lock:
            st = await self._storage.get_status(pod_name, timeout)
            if st is not None and st.exit_code is not None:
                await self._storage.delete(objs, timeout)
            return st
