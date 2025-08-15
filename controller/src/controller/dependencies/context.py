"""Request context management.

`ContextDependency` is an all-in-one dependency, because managing individual
dependencies turned out to be a real pain. It's designed to capture the
context of any request. It requires that a `~controller.config.Config` object
has been loaded before it can be instantiated.
"""

from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Request
from safir.dependencies.logger import logger_dependency
from structlog.stdlib import BoundLogger

from ..config import Config
from ..exceptions import NotConfiguredError
from ..factory import Factory, ProcessContext
from ..services.fileserver import FileserverManager
from ..services.fsadmin import FSAdminManager
from ..services.image import ImageService
from ..services.lab import LabManager

__all__ = [
    "ContextDependency",
    "RequestContext",
    "context_dependency",
]


@dataclass(slots=True)
class RequestContext:
    """Holds the incoming request and its surrounding context.

    This object is provided to every route handler via a dependency and
    contains the factory to create service objects, any global singletons that
    route handlers need to use, and other per-request information that is
    needed by route handlers.
    """

    request: Request
    """Incoming request."""

    logger: BoundLogger
    """Request logger, rebound with discovered context."""

    factory: Factory
    """Component factory."""

    image_service: ImageService
    """Global image service."""

    lab_manager: LabManager
    """User lab state."""

    fsadmin_manager: FSAdminManager
    """Filesystem admin state."""

    _fileserver_manager: FileserverManager | None
    """User fileserver state."""

    @property
    def fileserver_manager(self) -> FileserverManager:
        """File server manager, if file servers are configured."""
        if not self._fileserver_manager:
            raise NotConfiguredError("Fileserver is disabled in configuration")
        return self._fileserver_manager

    def rebind_logger(self, **values: Any) -> None:
        """Add the given values to the logging context.

        Parameters
        ----------
        **values
            Additional values that should be added to the logging context.
        """
        self.logger = self.logger.bind(**values)
        self.factory.set_logger(self.logger)


class ContextDependency:
    """Provide a per-request context as a FastAPI dependency.

    Each request gets its own `RequestContext`. The portions of the context
    shared across all requests are collected into the single process-global
    `~controller.factory.ProcessContext` and reused with each request.
    """

    def __init__(self) -> None:
        self._process_context: ProcessContext | None = None

    async def __call__(
        self,
        request: Request,
        logger: Annotated[BoundLogger, Depends(logger_dependency)],
    ) -> RequestContext:
        """Create a per-request context and return it."""
        if not self._process_context:
            raise RuntimeError("ContextDependency not initialized")
        factory = Factory(self._process_context, logger)
        fileserver_manager = None
        if self._process_context.config.fileserver.enabled:
            fileserver_manager = self._process_context.fileserver_manager
        return RequestContext(
            request=request,
            logger=logger,
            factory=factory,
            image_service=self._process_context.image_service,
            lab_manager=self._process_context.lab_manager,
            fsadmin_manager=self._process_context.fsadmin_manager,
            _fileserver_manager=fileserver_manager,
        )

    @property
    def is_initialized(self) -> bool:
        """Whether the process context has been initialized."""
        return self._process_context is not None

    async def initialize(self, config: Config) -> None:
        """Initialize the process-global shared context.

        Parameters
        ----------
        config
            Config for the lab controller.
        """
        if self._process_context:
            await self._process_context.stop()
        self._process_context = await ProcessContext.from_config(config)
        await self._process_context.start()

    async def aclose(self) -> None:
        """Clean up the per-process configuration."""
        if self._process_context:
            await self._process_context.stop()
            await self._process_context.aclose()
        self._process_context = None


context_dependency: ContextDependency = ContextDependency()
"""The dependency that will return the per-request context."""
