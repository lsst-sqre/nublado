"""The main application factory for the Nublado controller service."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import metadata, version

import structlog
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from safir.dependencies.http_client import http_client_dependency
from safir.fastapi import ClientRequestError, client_request_error_handler
from safir.kubernetes import initialize_kubernetes
from safir.logging import configure_logging, configure_uvicorn_logging
from safir.middleware.x_forwarded import XForwardedMiddleware
from safir.sentry import initialize_sentry
from safir.slack.webhook import SlackRouteErrorHandler

from .. import __version__
from .dependencies.config import config_dependency
from .dependencies.context import context_dependency
from .handlers import (
    files,
    fileserver,
    form,
    fsadmin,
    index,
    labs,
    prepuller,
    user_status,
)

__all__ = ["create_app"]


def create_app(*, load_config: bool = True) -> FastAPI:
    """Create the FastAPI application.

    This is in a function rather than using a global variable (as is more
    typical for FastAPI) because we want to defer configuration loading until
    after the test suite has a chance to override the path to the
    configuration file.

    Parameters
    ----------
    load_config
        If set to `False`, do not try to load the configuration and skip any
        setup that requires the configuration. This is used primarily for
        OpenAPI schema generation, where constructing the app is required but
        the configuration won't matter.
    """
    initialize_sentry(release=__version__)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await initialize_kubernetes()
        config = config_dependency.config
        await context_dependency.initialize(config)

        yield

        await context_dependency.aclose()
        await http_client_dependency.aclose()

    # Configure logging.
    if load_config:
        config = config_dependency.config
        configure_logging(
            name="controller",
            profile=config.log_profile,
            log_level=config.log_level,
        )
        configure_uvicorn_logging(config.log_level)

    # Create the application object.
    path_prefix = config.path_prefix if load_config else "/nublado"
    files_prefix = config.fileserver.path_prefix if load_config else "/files"
    app = FastAPI(
        title=config.name if load_config else "Nublado",
        description=metadata("nublado")["Summary"],
        version=version("nublado"),
        tags_metadata=[
            {
                "name": "hub",
                "description": "APIs that can only be used by JupyterHub.",
            },
            {
                "name": "user",
                "description": "APIs that can only be used by the user.",
            },
            {
                "name": "admin",
                "description": "APIs that can only be used by administrators.",
            },
            {
                "name": "internal",
                "description": (
                    "Internal routes used by the ingress and health checks."
                ),
            },
        ],
        openapi_url=f"{path_prefix}/openapi.json",
        docs_url=f"{path_prefix}/docs",
        redoc_url=f"{path_prefix}/redoc",
        lifespan=lifespan,
    )

    # Attach the main controller routers.
    app.include_router(index.internal_router)
    app.include_router(index.external_router, prefix=path_prefix)
    app.include_router(form.router, prefix=path_prefix)
    app.include_router(labs.router, prefix=path_prefix)
    app.include_router(prepuller.router, prefix=path_prefix)
    app.include_router(user_status.router, prefix=path_prefix)
    app.include_router(fileserver.router, prefix=path_prefix)
    app.include_router(fsadmin.router, prefix=path_prefix)

    # Attach the separate router for user file server creation.
    app.include_router(files.router, prefix=files_prefix)

    # Register middleware.
    app.add_middleware(XForwardedMiddleware)

    # Configure Slack alerts.
    if load_config and config.slack_webhook:
        webhook = config.slack_webhook
        logger = structlog.get_logger(__name__)
        SlackRouteErrorHandler.initialize(webhook, config.name, logger)
        logger.debug("Initialized Slack webhook")

    # Configure exception handlers.
    app.exception_handler(ClientRequestError)(client_request_error_handler)

    return app


def create_openapi() -> str:
    """Generate the OpenAPI schema.

    Returns
    -------
    str
        OpenAPI schema as serialized JSON.
    """
    app = create_app(load_config=False)
    description = app.description + "\n\n[Return to Nublado documentation](.)"
    schema = get_openapi(
        title=app.title,
        description=description,
        version=app.version,
        routes=app.routes,
    )
    return json.dumps(schema)
