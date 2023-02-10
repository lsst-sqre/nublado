"""The main application factory for the jupyterlab-controller service."""

from importlib.metadata import metadata, version
from pathlib import Path
from typing import Optional

import structlog
from fastapi import FastAPI, Request
from kubernetes_asyncio.config.config_exception import ConfigException
from safir.dependencies.http_client import http_client_dependency
from safir.kubernetes import initialize_kubernetes
from safir.logging import configure_logging, configure_uvicorn_logging
from safir.middleware.x_forwarded import XForwardedMiddleware
from starlette.datastructures import Headers

from .dependencies import context
from .dependencies.config import configuration_dependency
from .handlers import form, indexes, labs, prepuller, user_status

__all__ = ["create_app"]

# This seems like an awful way to do it.  FIXME?
injected_context_dependency: Optional[context.ContextDependency] = None

fake_request = Request(
    {
        "type": "http",
        "path": "/",
        "headers": Headers({"X-Auth-Request-Token": "dummy"}).raw,
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "client": {"127.0.0.1", 8080},
        "server": {"127.0.0.1", 8080},
    }
)


def create_app(
    *,
    config_dir: Optional[Path] = None,
    context_dependency: Optional[context.ContextDependency] = None,
) -> FastAPI:
    """Create the FastAPI application.

    This is in a function rather than using a global variable (as is more
    typical for FastAPI) because some middleware depends on configuration
    settings and we therefore want to recreate the application between tests.
    """
    # We need to be able to override the config location for testing
    # and running locally.
    #
    # If config_dir is set, we will assume that it contains the path
    # to a directory that contains both 'config.yaml' and
    # 'docker_config.json'.
    if config_dir is not None:
        configuration_dependency.set_path(config_dir / "config.yaml")
    config = configuration_dependency.config

    # If ProcessContext is supplied, we use it instead of initializing a
    # new one.  The only way I can see to make the linkage at app startup
    # work right now is via a process global, which seems hideous.
    if context_dependency is not None:
        global injected_context_dependency
        injected_context_dependency = context_dependency

    # Configure logging.
    configure_logging(
        profile=config.safir.profile,
        log_level=config.safir.log_level,
        name=config.safir.logger_name,
    )
    configure_uvicorn_logging(config.safir.log_level)

    # Create the application object.
    app = FastAPI(
        title=config.safir.name,
        description=metadata("jupyterlab-controller")["Summary"],
        version=version("jupyterlab-controller"),
        openapi_url=f"/{config.safir.root_endpoint}/openapi.json",
        docs_url=f"/{config.safir.root_endpoint}/docs",
        redoc_url=f"/{config.safir.root_endpoint}/redoc",
    )

    # Attach the routers.
    app.include_router(indexes.internal_index_router)
    app.include_router(
        indexes.external_index_router, prefix=f"/{config.safir.root_endpoint}"
    )
    spawner = f"{config.safir.root_endpoint}/spawner/v1"
    app.include_router(labs.router, prefix=f"/{spawner}/labs")
    app.include_router(user_status.router, prefix=f"/{spawner}/user-status")
    app.include_router(form.router, prefix=f"/{spawner}/lab-form")
    app.include_router(prepuller.router, prefix=f"/{spawner}")

    # Register lifecycle handlers.
    app.on_event("startup")(startup_event)
    app.on_event("shutdown")(shutdown_event)

    # Register middleware.
    app.add_middleware(XForwardedMiddleware)

    return app


async def startup_event() -> None:
    global context_dependency
    k_str = ""
    try:
        await initialize_kubernetes()
    except ConfigException as exc:
        # This only happens in GH CI, and it's harmless because we don't
        # make any actual K8s calls in the test suite--it's all mocked out.
        #
        # But we have to sit on the error until we have something to log it
        # with.
        #
        # If we really don't have K8s configuration, we'll fall apart as soon
        # as we start the prepuller executor just below.
        k_str = str(exc)
    if injected_context_dependency is not None:
        context.context_dependency = injected_context_dependency
    config = configuration_dependency.config
    await context.context_dependency.initialize(config)
    logger = structlog.get_logger(name=config.safir.logger_name)
    if k_str:
        logger.warning(k_str)
    ctx = await context.context_dependency(request=fake_request, logger=logger)
    executor = ctx.prepuller_executor
    await executor.start()
    lab_manager = ctx.lab_manager
    await lab_manager.reconcile_user_map()


async def shutdown_event() -> None:
    config = configuration_dependency.config
    ctx = await context.context_dependency(
        request=fake_request,
        logger=structlog.get_logger(name=config.safir.logger_name),
    )
    executor = ctx.prepuller_executor
    await executor.stop()
    await http_client_dependency.aclose()
