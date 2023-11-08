"""The main application factory for the Nublado controller service."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import metadata, version

import structlog
from fastapi import FastAPI
from safir.dependencies.http_client import http_client_dependency
from safir.fastapi import ClientRequestError, client_request_error_handler
from safir.kubernetes import initialize_kubernetes
from safir.logging import configure_logging, configure_uvicorn_logging
from safir.middleware.x_forwarded import XForwardedMiddleware
from safir.slack.webhook import SlackRouteErrorHandler
from sse_starlette.sse import AppStatus

from .dependencies.config import config_dependency
from .dependencies.context import context_dependency
from .handlers import fileserver, form, index, labs, prepuller, user_status

__all__ = ["create_app"]


def create_app() -> FastAPI:
    """Create the FastAPI application.

    This is in a function rather than using a global variable (as is more
    typical for FastAPI) because we want to defer configuration loading until
    after the test suite has a chance to override the path to the
    configuration file.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await initialize_kubernetes()
        config = config_dependency.config
        await context_dependency.initialize(config)

        yield

        await context_dependency.aclose()
        await http_client_dependency.aclose()

        # sse-starlette initializes this process-global variable when it is
        # first invoked, but it's per-event-loop, and therefore breaks tests
        # when each test is run in a separate event loop. Clear the variable
        # to force reinitialization on app shutdown so that each event loop
        # will get its own.
        #
        # See https://github.com/sysid/sse-starlette/issues/59
        AppStatus.should_exit_event = None

    # Configure logging.
    config = config_dependency.config
    configure_logging(
        name="controller",
        profile=config.safir.profile,
        log_level=config.safir.log_level,
    )
    configure_uvicorn_logging(config.safir.log_level)

    # Create the application object.
    app = FastAPI(
        title=config.safir.name,
        description=metadata("controller")["Summary"],
        version=version("controller"),
        openapi_url=f"{config.safir.path_prefix}/openapi.json",
        docs_url=f"{config.safir.path_prefix}/docs",
        redoc_url=f"{config.safir.path_prefix}/redoc",
        lifespan=lifespan,
    )

    # Attach the routers.
    app.include_router(index.internal_router)
    app.include_router(index.external_router, prefix=config.safir.path_prefix)
    app.include_router(form.router, prefix=config.safir.path_prefix)
    app.include_router(labs.router, prefix=config.safir.path_prefix)
    app.include_router(prepuller.router, prefix=config.safir.path_prefix)
    app.include_router(user_status.router, prefix=config.safir.path_prefix)
    app.include_router(
        fileserver.user_router, prefix=config.fileserver.path_prefix
    )
    app.include_router(fileserver.router, prefix=config.safir.path_prefix)

    # Register middleware.
    app.add_middleware(XForwardedMiddleware)

    # Configure Slack alerts.
    logger = structlog.get_logger(__name__)
    if config.slack_webhook:
        webhook = config.slack_webhook
        SlackRouteErrorHandler.initialize(webhook, config.safir.name, logger)
        logger.debug("Initialized Slack webhook")

    # Configure exception handlers.
    app.exception_handler(ClientRequestError)(client_request_error_handler)

    return app
