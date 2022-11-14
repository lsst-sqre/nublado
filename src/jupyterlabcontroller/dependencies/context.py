"""
ContextDependency is an all-in-one dependency, because managing
individual dependencies turned out to be a real pain.  It's designed to
capture the context of any request.  It requires that a Config has been
loaded before it can be instantiated.
"""

from fastapi import Depends, Request
from httpx import AsyncClient
from safir.dependencies.http_client import http_client_dependency
from safir.dependencies.logger import logger_dependency
from structlog.stdlib import BoundLogger

from ..config import Config
from ..models.context import Context
from .config import configuration_dependency


class ContextDependency:
    async def __call__(
        self,
        request: Request,
        config: Config = Depends(configuration_dependency),
        http_client: AsyncClient = Depends(http_client_dependency),
        logger: BoundLogger = Depends(logger_dependency),
    ) -> Context:
        context: Context = Context.initialize(
            config=config,
            http_client=http_client,
            logger=logger,
        )
        await context.patch_with_request(request)
        return context


context_dependency = ContextDependency()
