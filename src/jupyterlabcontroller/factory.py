"""Component factory and global and per-request context management."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import aclosing, asynccontextmanager
from dataclasses import dataclass
from typing import Optional, Self

import structlog
from httpx import AsyncClient
from kubernetes_asyncio.client.api_client import ApiClient
from safir.dependencies.http_client import http_client_dependency
from structlog.stdlib import BoundLogger

from .config import Configuration
from .constants import KUBERNETES_REQUEST_TIMEOUT
from .models.domain.usermap import UserMap
from .services.events import EventManager
from .services.form import FormManager
from .services.image import ImageService
from .services.lab import LabManager
from .services.prepuller import Prepuller
from .storage.docker import DockerStorageClient
from .storage.gafaelfawr import GafaelfawrStorageClient
from .storage.k8s import K8sStorageClient


@dataclass(frozen=True, slots=True)
class ProcessContext:
    """Per-process global application state.

    This object holds all of the per-process singletons and is managed by
    `~jupyterlabcontroller.dependencies.context.ContextDependency`. It is used
    by the `Factory` class as a source of dependencies to inject into created
    service and storage objects, and by the context dependency as a source of
    singletons that should also be exposed to route handlers via the request
    context.
    """

    config: Configuration
    """Lab controller configuration."""

    http_client: AsyncClient
    """Shared HTTP client."""

    k8s_client: K8sStorageClient
    """Shared Kubernetes client."""

    image_service: ImageService
    """Image service."""

    prepuller: Prepuller
    """Prepuller."""

    user_map: UserMap
    """State management for user lab pods."""

    event_manager: EventManager
    """Manager for lab spawning events."""

    @classmethod
    async def from_config(
        cls,
        config: Configuration,
        k8s_client: Optional[K8sStorageClient] = None,
    ) -> Self:
        """Create a new process context from the controller configuration.

        Parameters
        ----------
        config
            Lab controller configuration.
        k8s_client
            Kubernetes storage object to use. Used by the test suite for
            dependency injection.

        Returns
        -------
        ProcessContext
            Shared context for a lab controller process.
        """
        http_client = await http_client_dependency()

        # This logger is used only by process-global singletons.  Everything
        # else will use a per-request logger that includes more context about
        # the request (such as the authenticated username).
        logger = structlog.get_logger(config.safir.logger_name)

        if not k8s_client:
            k8s_api_client = ApiClient()
            k8s_client = K8sStorageClient(
                k8s_api=k8s_api_client,
                timeout=KUBERNETES_REQUEST_TIMEOUT,
                logger=logger,
            )

        docker_client = DockerStorageClient(
            credentials_path=config.docker_secrets_path,
            http_client=http_client,
            logger=logger,
        )
        image_service = ImageService(
            config=config.images,
            docker=docker_client,
            kubernetes=k8s_client,
            logger=logger,
        )
        return cls(
            config=config,
            http_client=http_client,
            k8s_client=k8s_client,
            image_service=image_service,
            prepuller=Prepuller(
                config=config.images,
                namespace=config.lab.namespace_prefix,
                image_service=image_service,
                k8s_client=k8s_client,
                logger=logger,
            ),
            user_map=UserMap(),
            event_manager=EventManager(logger=logger),
        )

    async def start(self) -> None:
        """Start the background threads running."""
        await self.image_service.start()
        await self.prepuller.start()

    async def stop(self) -> None:
        """Clean up a process context.

        Called during shutdown, or before recreating the process context using
        a different configuration.
        """
        await self.prepuller.stop()
        await self.image_service.stop()


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
    async def standalone(
        cls, config: Configuration, context: Optional[ProcessContext] = None
    ) -> AsyncIterator[Self]:
        """Async context manager for lab controller components.

        Intended for background jobs or the test suite.

        Parameters
        ----------
        config
            Lab controller configuration
        context
            Shared process context. If not provided, a new one will be
            constructed.

        Yields
        ------
        Factory
            Newly-created factory. Must be used as a context manager.
        """
        logger = structlog.get_logger(config.safir.logger_name)
        if not context:
            context = await ProcessContext.from_config(config)
        factory = cls(context, logger)
        async with aclosing(factory):
            yield factory

    def __init__(self, context: ProcessContext, logger: BoundLogger) -> None:
        self._context = context
        self._logger = logger

    @property
    def image_service(self) -> ImageService:
        """Global image service, from the `ProcessContext`.

        Only used by tests; handlers have access to the image service via the
        request context.
        """
        return self._context.image_service

    @property
    def user_map(self) -> UserMap:
        """Current user lab status, from the `ProcessContext`.

        Only used by tests; handlers have access to the user map via the
        request context.
        """
        return self._context.user_map

    async def aclose(self) -> None:
        """Shut down the factory.

        After this method is called, the factory object is no longer valid and
        must not be used.
        """
        await self._context.stop()

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
        return FormManager(
            image_service=self._context.image_service,
            lab_sizes=self._context.config.lab.sizes,
            logger=self._logger,
        )

    def create_gafaelfawr_client(self) -> GafaelfawrStorageClient:
        return GafaelfawrStorageClient(
            config=self._context.config,
            http_client=self._context.http_client,
            logger=self._logger,
        )

    def create_lab_manager(self) -> LabManager:
        return LabManager(
            instance_url=self._context.config.base_url,
            manager_namespace=self._context.config.lab.namespace_prefix,
            user_map=self._context.user_map,
            event_manager=self._context.event_manager,
            image_service=self._context.image_service,
            logger=self._logger,
            lab_config=self._context.config.lab,
            k8s_client=self._context.k8s_client,
        )

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
