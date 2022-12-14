"""The main application factory for the jupyterlab-controller service.

Notes
-----
Be aware that, following the normal pattern for FastAPI services, the app is
constructed when this module is loaded and is not deferred until a function is
called.
"""

from importlib.metadata import metadata, version
from typing import Optional

import structlog
from fastapi import FastAPI, Request
from safir.dependencies.http_client import http_client_dependency
from safir.kubernetes import initialize_kubernetes
from safir.logging import configure_logging, configure_uvicorn_logging
from safir.middleware.x_forwarded import XForwardedMiddleware
from starlette.datastructures import Headers

from .dependencies import context
from .dependencies.config import configuration_dependency
from .handlers import external_router, internal_router

__all__ = ["create_app"]

# This seems like an awful way to do it.  FIXME?
injected_context_dependency: Optional[context.ContextDependency] = None

fake_request = Request(
    {
        "type": "http",
        "path": "/",
        "headers": Headers({"Authorization": "Bearer nobody"}).raw,
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "client": {"127.0.0.1", 8080},
        "server": {"127.0.0.1", 8080},
    }
)


def create_app(
    *,
    config_dir: Optional[str] = None,
    context_dependency: Optional[context.ContextDependency] = None,
) -> FastAPI:
    """Create the FastAPI application.

    This is in a function rather than using a global variable (as is more
    typical for FastAPI) because some middleware depends on configuration
    settings and we therefore want to recreate the application between tests.

    Stolen from Gafaelfawr.
    """

    #
    # We need to be able to override the config location for testing
    # and running locally.
    #
    # If config_dir is set, we will assume that it contains the path
    # to a directory that contains both 'config.yaml' and
    # 'docker_config.json'.
    #
    # If ProcessContext is supplied, we use it instead of initializing a
    # new one.  The only way I can see to make the linkage at app startup
    # work right now is via a process global, which seems hideous.

    if config_dir is not None:
        configuration_dependency.set_filename(f"{config_dir}/config.yaml")
    config = configuration_dependency.config

    if context_dependency is not None:
        global injected_context_dependency
        injected_context_dependency = context_dependency

    configure_logging(
        profile=config.safir.profile,
        log_level=config.safir.log_level,
        name=config.safir.logger_name,
    )
    configure_uvicorn_logging(config.safir.log_level)

    app = FastAPI(
        title=config.safir.name,
        description=metadata("jupyterlab-controller")["Summary"],
        version=version("jupyterlab-controller"),
        openapi_url=f"/{config.safir.root_endpoint}/openapi.json",
        docs_url=f"/{config.safir.root_endpoint}/docs",
        redoc_url=f"/{config.safir.root_endpoint}/redoc",
    )

    """The main FastAPI application for jupyterlab-controller."""

    # Attach the routers.
    app.include_router(internal_router)
    app.include_router(
        external_router, prefix=f"/{config.safir.root_endpoint}"
    )

    # Register lifecycle handlers.
    app.on_event("startup")(startup_event)
    app.on_event("shutdown")(shutdown_event)

    app.add_middleware(XForwardedMiddleware)

    return app


async def startup_event() -> None:
    global context_dependency
    await initialize_kubernetes()
    if injected_context_dependency is not None:
        context.context_dependency = injected_context_dependency
    config = configuration_dependency.config
    await context.context_dependency.initialize(config)
    ctx = await context.context_dependency(
        request=fake_request,
        logger=structlog.get_logger(name=config.safir.logger_name),
    )
    executor = ctx.prepuller_executor
    await executor.start()


async def shutdown_event() -> None:
    config = configuration_dependency.config
    ctx = await context.context_dependency(
        request=fake_request,
        logger=structlog.get_logger(name=config.safir.logger_name),
    )
    executor = ctx.prepuller_executor
    await executor.stop()
    await http_client_dependency.aclose()
