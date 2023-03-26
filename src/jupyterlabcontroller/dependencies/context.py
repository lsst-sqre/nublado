"""
ContextDependency is an all-in-one dependency, because managing
individual dependencies turned out to be a real pain.  It's designed to
capture the context of any request.  It requires that a Config has been
loaded before it can be instantiated.
"""

from dataclasses import dataclass
from typing import Any, Optional

import structlog
from fastapi import Depends, Request
from safir.dependencies.logger import logger_dependency
from structlog.stdlib import BoundLogger

from ..config import Config
from ..factory import Factory, ProcessContext
from ..models.domain.usermap import UserMap
from ..services.events import EventManager
from ..services.image import ImageService


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

    user_map: UserMap
    """Global user lab state."""

    event_manager: EventManager
    """Global manager of user lab spawning events."""

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
    `~jupyterlabcontroller.factory.ProcessContext` and reused with each
    request.
    """

    def __init__(self) -> None:
        self._process_context: Optional[ProcessContext] = None

    async def __call__(
        self,
        request: Request,
        logger: BoundLogger = Depends(logger_dependency),
    ) -> RequestContext:
        """Creates a per-request context and returns it."""
        if not self._process_context:
            raise RuntimeError("ContextDependency not initialized")
        factory = Factory(self._process_context, logger)
        return RequestContext(
            request=request,
            logger=logger,
            factory=factory,
            image_service=self._process_context.image_service,
            user_map=self._process_context.user_map,
            event_manager=self._process_context.event_manager,
        )

    async def initialize(self, config: Config) -> None:
        """Initialize the process-global shared context.

        If the process context was overriden by `override_process_context`,
        use the existing one rather than recreating it.  This allows the test
        suite to inject a process context before application initialization.

        Parameters
        ----------
        config
            Config for the lab controller.
        """
        if self._process_context:
            await self._process_context.stop()
        self._process_context = await ProcessContext.from_config(config)
        await self._process_context.start()

        # This is an ugly hack to do an initial reconciliation of the user
        # map. That functionality is currently in the lab manager, which has
        # tons of other dependencies and isn't a global singleton, so we have
        # to create a factory just to create a lab manager to do the initial
        # reconciliation. This needs some rethinking.
        logger = structlog.get_logger(__name__)
        factory = Factory(self._process_context, logger)
        lab_manager = factory.create_lab_manager()
        await lab_manager.reconcile_user_map()

    async def aclose(self) -> None:
        """Clean up the per-process configuration."""
        if self._process_context:
            await self._process_context.stop()
        self._process_context = None


context_dependency = ContextDependency()
"""The dependency that will return the per-request context."""
