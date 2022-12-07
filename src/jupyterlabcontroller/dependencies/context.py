"""
ContextDependency is an all-in-one dependency, because managing
individual dependencies turned out to be a real pain.  It's designed to
capture the context of any request.  It requires that a Configuration has been
loaded before it can be instantiated.
"""

from typing import Optional

from fastapi import Depends, Header, HTTPException, Request
from httpx import AsyncClient
from safir.dependencies.http_client import http_client_dependency
from safir.dependencies.logger import logger_dependency
from structlog.stdlib import BoundLogger

from ..config import Configuration
from ..factory import Factory, ProcessContext
from ..models.context import Context
from ..util import extract_bearer_token


class ContextDependency:
    """Provide a per-request context as a FastAPI dependency.

    Each request gets its own `RequestContext`; however the portions of the
    context shared across all requests will be collected into the single
    process-global `~jupyterlabcontroller.factory.ProcessContext` and
    reused with each request.
    """

    def __init__(self) -> None:
        self._config: Optional[Configuration] = None
        self._process_context: Optional[ProcessContext] = None

    async def __call__(
        self,
        request: Request,
        http_client: AsyncClient = Depends(http_client_dependency),
        logger: BoundLogger = Depends(logger_dependency),
        authorization: str = Header(...),
    ) -> Context:
        """Creates a per-request context and returns it."""
        if self._config is None or self._process_context is None:
            raise RuntimeError("ContextDependency not initialized")
        if request.client and request.client.host:
            ip_address = request.client.host
        else:
            raise HTTPException(
                status_code=422,
                detail={
                    "msg": "No client IP address",
                    "type": "missing_client_ip",
                },
            )
        token = extract_bearer_token(authorization)
        return Context(
            ip_address=ip_address,
            config=self._config,
            logger=logger,
            http_client=http_client,
            token=token,
            _factory=Factory(self._process_context, logger),
        )

    @property
    def process_context(self) -> ProcessContext:
        """The underlying process context, primarily for use in tests."""
        if not self._process_context:
            raise RuntimeError("ContextDependency not initialized")
        return self._process_context

    async def initialize(self, config: Configuration) -> None:
        """Initialize the process-global shared context."""

        if self._process_context:
            await self._process_context.aclose()
        self._config = config
        self._process_context = await ProcessContext.from_config(config)

    async def aclose(self) -> None:
        """Clean up the per-process configuration."""
        if self._process_context:
            await self._process_context.aclose()
        self._config = None
        self._process_context = None


context_dependency = ContextDependency()
"""The dependency that will return the per-request context."""
