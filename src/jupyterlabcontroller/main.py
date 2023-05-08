"""The main application factory for the jupyterlab-controller service."""

from importlib.metadata import metadata, version

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from safir.dependencies.http_client import http_client_dependency
from safir.kubernetes import initialize_kubernetes
from safir.logging import configure_logging, configure_uvicorn_logging
from safir.middleware.x_forwarded import XForwardedMiddleware
from safir.slack.webhook import SlackRouteErrorHandler

from .dependencies.config import configuration_dependency
from .dependencies.context import context_dependency
from .exceptions import ClientRequestError
from .handlers import fileserver, form, index, labs, prepuller, user_status

__all__ = ["create_app"]


def create_app() -> FastAPI:
    """Create the FastAPI application.

    This is in a function rather than using a global variable (as is more
    typical for FastAPI) because we want to defer configuration loading until
    after the test suite has a chance to override the path to the
    configuration file.
    """
    config = configuration_dependency.config

    # Configure logging.
    configure_logging(
        name="jupyterlabcontroller",
        profile=config.safir.profile,
        log_level=config.safir.log_level,
    )
    configure_uvicorn_logging(config.safir.log_level)

    # Create the application object.
    app = FastAPI(
        title=config.safir.name,
        description=metadata("jupyterlab-controller")["Summary"],
        version=version("jupyterlab-controller"),
        openapi_url=f"{config.safir.path_prefix}/openapi.json",
        docs_url=f"{config.safir.path_prefix}/docs",
        redoc_url=f"{config.safir.path_prefix}/redoc",
    )

    logger = structlog.get_logger(__name__)
    # Attach the routers.
    app.include_router(index.internal_router)
    app.include_router(index.external_router, prefix=config.safir.path_prefix)
    app.include_router(form.router, prefix=config.safir.path_prefix)
    app.include_router(labs.router, prefix=config.safir.path_prefix)
    app.include_router(prepuller.router, prefix=config.safir.path_prefix)
    app.include_router(user_status.router, prefix=config.safir.path_prefix)
    if config.fileserver.enabled:
        logger.info("Enabling fileserver routes.")
        app.include_router(
            fileserver.user_router, prefix=config.fileserver.path_prefix
        )
        app.include_router(fileserver.router, prefix=config.safir.path_prefix)

    # Register middleware.
    app.add_middleware(XForwardedMiddleware)

    # Configure Slack alerts.
    if config.slack_webhook:
        webhook = config.slack_webhook
        SlackRouteErrorHandler.initialize(webhook, config.safir.name, logger)
        logger.debug("Initialized Slack webhook")

    @app.on_event("startup")
    async def startup_event() -> None:
        await initialize_kubernetes()
        config = configuration_dependency.config
        await context_dependency.initialize(config)

    @app.on_event("shutdown")
    async def shutdown_event() -> None:
        await context_dependency.aclose()
        await http_client_dependency.aclose()

    @app.exception_handler(ClientRequestError)
    async def client_error_handler(
        request: Request, exc: ClientRequestError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code, content={"detail": [exc.to_dict()]}
        )

    return app
