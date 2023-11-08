"""Component factory and global and per-request context management."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import aclosing, asynccontextmanager
from dataclasses import dataclass
from typing import Self

import structlog
from httpx import AsyncClient
from kubernetes_asyncio.client.api_client import ApiClient
from safir.dependencies.http_client import http_client_dependency
from safir.slack.webhook import SlackWebhookClient
from structlog.stdlib import BoundLogger

from .config import Config
from .exceptions import NotConfiguredError
from .models.v1.prepuller_config import DockerSourceConfig, GARSourceConfig
from .services.builder.fileserver import FileserverBuilder
from .services.builder.lab import LabBuilder
from .services.builder.prepuller import PrepullerBuilder
from .services.fileserver import FileserverManager
from .services.form import FormManager
from .services.image import ImageService
from .services.lab import LabManager
from .services.prepuller import Prepuller
from .services.size import SizeManager
from .services.source.base import ImageSource
from .services.source.docker import DockerImageSource
from .services.source.gar import GARImageSource
from .storage.docker import DockerStorageClient
from .storage.gafaelfawr import GafaelfawrStorageClient
from .storage.gar import GARStorageClient
from .storage.kubernetes.fileserver import FileserverStorage
from .storage.kubernetes.lab import LabStorage
from .storage.kubernetes.node import NodeStorage
from .storage.kubernetes.pod import PodStorage
from .storage.metadata import MetadataStorage


@dataclass(frozen=True, slots=True)
class ProcessContext:
    """Per-process global application state.

    This object holds all of the per-process singletons and is managed by
    `~controller.dependencies.context.ContextDependency`. It is used by the
    `Factory` class as a source of dependencies to inject into created service
    and storage objects, and by the context dependency as a source of
    singletons that should also be exposed to route handlers via the request
    context.
    """

    config: Config
    """Lab controller configuration."""

    http_client: AsyncClient
    """Shared HTTP client."""

    kubernetes_client: ApiClient
    """Shared Kubernetes client."""

    image_service: ImageService
    """Image service."""

    prepuller: Prepuller
    """Prepuller."""

    lab_manager: LabManager
    """State management for user lab pods."""

    _fileserver_manager: FileserverManager | None
    """State management for user file servers."""

    @classmethod
    async def from_config(cls, config: Config) -> Self:
        """Create a new process context from the controller configuration.

        Parameters
        ----------
        config
            Lab controller configuration.

        Returns
        -------
        ProcessContext
            Shared context for a lab controller process.
        """
        http_client = await http_client_dependency()
        kubernetes_client = ApiClient()

        # This logger is used only by process-global singletons.  Everything
        # else will use a per-request logger that includes more context about
        # the request (such as the authenticated username).
        logger = structlog.get_logger(__name__)

        slack_client = None
        if config.slack_webhook:
            slack_client = SlackWebhookClient(
                config.slack_webhook, config.safir.name, logger
            )

        match config.images.source:
            case DockerSourceConfig():
                docker_client = DockerStorageClient(
                    credentials_path=config.docker_secrets_path,
                    http_client=http_client,
                    logger=logger,
                )
                source: ImageSource = DockerImageSource(
                    config=config.images.source,
                    docker=docker_client,
                    logger=logger,
                )
            case GARSourceConfig():
                gar_client = GARStorageClient(logger)
                source = GARImageSource(
                    config=config.images.source, gar=gar_client, logger=logger
                )

        fileserver_manager = None
        if config.fileserver.enabled:
            fileserver_builder = FileserverBuilder(
                config=config.fileserver,
                instance_url=config.base_url,
                volumes=config.lab.volumes,
                logger=logger,
            )
            fileserver_manager = FileserverManager(
                config=config.fileserver,
                fileserver_builder=fileserver_builder,
                fileserver_storage=FileserverStorage(
                    kubernetes_client, logger
                ),
                slack_client=slack_client,
                logger=logger,
            )

        metadata_storage = MetadataStorage(config.metadata_path)
        image_service = ImageService(
            config=config.images,
            source=source,
            node_storage=NodeStorage(kubernetes_client, logger),
            slack_client=slack_client,
            logger=logger,
        )
        size_manager = SizeManager(config.lab.sizes)
        lab_builder = LabBuilder(
            config=config.lab,
            size_manager=size_manager,
            instance_url=config.base_url,
            logger=logger,
        )
        return cls(
            config=config,
            http_client=http_client,
            image_service=image_service,
            kubernetes_client=kubernetes_client,
            prepuller=Prepuller(
                image_service=image_service,
                prepuller_builder=PrepullerBuilder(
                    metadata_storage=metadata_storage,
                    pull_secret=config.lab.pull_secret,
                ),
                metadata_storage=metadata_storage,
                pod_storage=PodStorage(kubernetes_client, logger),
                slack_client=slack_client,
                logger=logger,
            ),
            lab_manager=LabManager(
                config=config.lab,
                lab_builder=lab_builder,
                size_manager=size_manager,
                image_service=image_service,
                metadata_storage=metadata_storage,
                lab_storage=LabStorage(kubernetes_client, logger),
                slack_client=slack_client,
                logger=logger,
            ),
            _fileserver_manager=fileserver_manager,
        )

    @property
    def fileserver_manager(self) -> FileserverManager:
        """File server manager, if file servers are configured."""
        if not self._fileserver_manager:
            raise NotConfiguredError("Fileserver is disabled in configuration")
        return self._fileserver_manager

    async def aclose(self) -> None:
        """Free allocated resources."""
        await self.kubernetes_client.close()

    async def start(self) -> None:
        """Start the background threads running."""
        await self.image_service.start()
        await self.prepuller.start()
        await self.lab_manager.start()
        if self._fileserver_manager:
            await self._fileserver_manager.start()

    async def stop(self) -> None:
        """Clean up a process context.

        Called during shutdown, or before recreating the process context using
        a different configuration.
        """
        if self._fileserver_manager:
            await self._fileserver_manager.stop()
        await self.prepuller.stop()
        await self.image_service.stop()
        await self.lab_manager.stop()


class Factory:
    """Build lab controller components.

    Uses the contents of a `ProcessContext` to construct the components of the
    application on demand.

    Parameters
    ----------
    context
        Shared process context.
    logger
        Logger to use for messages.
    """

    @classmethod
    @asynccontextmanager
    async def standalone(cls, config: Config) -> AsyncIterator[Self]:
        """Async context manager for lab controller components.

        Intended for background jobs or the test suite.

        Parameters
        ----------
        config
            Lab controller configuration

        Yields
        ------
        Factory
            Newly-created factory. Must be used as a context manager.
        """
        logger = structlog.get_logger(__name__)
        context = await ProcessContext.from_config(config)
        factory = cls(context, logger)
        async with aclosing(factory):
            yield factory

    def __init__(self, context: ProcessContext, logger: BoundLogger) -> None:
        self._context = context
        self._logger = logger
        self._background_services_started = False

    @property
    def image_service(self) -> ImageService:
        """Global image service, from the `ProcessContext`.

        Only used by tests; handlers have access to the image service via the
        request context.
        """
        return self._context.image_service

    @property
    def lab_manager(self) -> LabManager:
        """Global lab manager, from the `ProcessContext`.

        Only used by tests; handlers have access to the lab manager via the
        request context.
        """
        return self._context.lab_manager

    @property
    def prepuller(self) -> Prepuller:
        """Global prepuller, from the `ProcessContext`.

        Only used by tests; handlers don't need access to the prepuller.
        """
        return self._context.prepuller

    async def aclose(self) -> None:
        """Shut down the factory.

        After this method is called, the factory object is no longer valid and
        must not be used.
        """
        if self._background_services_started:
            await self._context.stop()
        await self._context.aclose()

    def create_docker_storage(self) -> DockerStorageClient:
        """Create a Docker storage client.

        Returns
        -------
        DockerStorageClient
            Newly-created Docker storage client.
        """
        return DockerStorageClient(
            credentials_path=self._context.config.docker_secrets_path,
            http_client=self._context.http_client,
            logger=self._logger,
        )

    def create_form_manager(self) -> FormManager:
        """Create service to generate lab spawning forms.

        Returns
        -------
        FormManager
            Newly-created form manager.
        """
        return FormManager(
            image_service=self._context.image_service,
            lab_sizes=self._context.config.lab.sizes,
            logger=self._logger,
        )

    def create_gafaelfawr_client(self) -> GafaelfawrStorageClient:
        """Create client to look up users in Gafaelfawr.

        Returns
        -------
        GafaelfawrStorageClient
            Newly-created Gafaelfawr client.
        """
        return GafaelfawrStorageClient(
            config=self._context.config,
            http_client=self._context.http_client,
            logger=self._logger,
        )

    def create_lab_builder(self) -> LabBuilder:
        """Create builder service for user labs.

        Returns
        -------
        LabBuilder
            Newly-created lab builder.
        """
        return LabBuilder(
            config=self._context.config.lab,
            size_manager=self.create_size_manager(),
            instance_url=self._context.config.base_url,
            logger=self._logger,
        )

    def create_lab_storage(self) -> LabStorage:
        """Create Kubernetes storage object for user labs.

        Returns
        -------
        LabStorage
            Newly-created lab storage.
        """
        return LabStorage(self._context.kubernetes_client, self._logger)

    def create_size_manager(self) -> SizeManager:
        """Create service to map between named sizes and resource amounts.

        Returns
        -------
        SizeManager
            Newly-created size manager.
        """
        return SizeManager(self._context.config.lab.sizes)

    def set_logger(self, logger: BoundLogger) -> None:
        """Replace the internal logger.

        Used by the context dependency to update the logger for all
        newly-created components when it's rebound with additional context.

        Parameters
        ----------
        logger
            New logger.
        """
        self._logger = logger

    async def start_background_services(self) -> None:
        """Start global background services managed by the process context.

        These are normally started by the context dependency when running as a
        FastAPI app, but the test suite may want the background processes
        running while testing with only a factory.

        Only used by the test suite.
        """
        await self._context.start()
        self._background_services_started = True

    async def stop_background_services(self) -> None:
        """Stop global background services managed by the process context.

        These are normally stopped when closing down the global context, but
        the test suite may want to stop and start them independently.

        Only used by the test suite.
        """
        if self._background_services_started:
            await self._context.stop()
        self._background_services_started = False
