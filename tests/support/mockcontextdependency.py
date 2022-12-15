from typing import Optional

import structlog
from fastapi import Request
from structlog.stdlib import BoundLogger

from jupyterlabcontroller.config import Configuration
from jupyterlabcontroller.dependencies.context import ContextDependency
from jupyterlabcontroller.factory import Factory

from ..settings import TestObjectFactory
from .mockcontext import MockContext
from .mockprocesscontext import MockProcessContext


class MockContextDependency(ContextDependency):
    def __init__(self, test_obj: TestObjectFactory) -> None:
        self._test_obj = test_obj
        self._config: Optional[Configuration] = None
        self._process_context: Optional[MockProcessContext] = None

    async def initialize(self, config: Configuration) -> None:
        """Initialize the process-global shared context, except this one
        returns mocked-out versions of the storage clients"""
        self._config = config
        if self._process_context:
            await self._process_context.aclose()
        self._process_context = await MockProcessContext.create(
            config, self._test_obj
        )

    async def __call__(
        self,
        request: Request,
        logger: BoundLogger = structlog.get_logger(
            "jupyterlabcontroller-test"
        ),
        x_auth_request_token: str = "token-of-affection",
    ) -> MockContext:
        if self._process_context is None:
            raise RuntimeError("process_context cannot be None")
        ctx = await super().__call__(
            request=request,
            logger=logger,
            x_auth_request_token=x_auth_request_token,
        )
        return MockContext(
            token=ctx.token,
            ip_address=ctx.ip_address,
            logger=logger,
            _factory=Factory(
                context=self._process_context,
                logger=logger,
            ),
            test_obj=self._test_obj,
        )
