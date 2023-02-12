"""The main application factory for the jupyterlab-controller service."""

from importlib.metadata import metadata, version

import structlog
from fastapi import FastAPI
from kubernetes_asyncio.config.config_exception import ConfigException
from safir.dependencies.http_client import http_client_dependency
from safir.kubernetes import initialize_kubernetes
from safir.logging import configure_logging, configure_uvicorn_logging
from safir.middleware.x_forwarded import XForwardedMiddleware

from .dependencies.config import configuration_dependency
from .dependencies.context import context_dependency
from .handlers import form, indexes, labs, prepuller, user_status

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

    # Register middleware.
    app.add_middleware(XForwardedMiddleware)

    @app.on_event("startup")
    async def startup_event() -> None:
        k_str = ""
        try:
            await initialize_kubernetes()
        except ConfigException as exc:
            # This only happens in GH CI, and it's harmless because we don't
            # make any actual K8s calls in the test suite--it's all mocked
            # out.
            #
            # But we have to sit on the error until we have something to log
            # it with.
            #
            # If we really don't have K8s configuration, we'll fall apart as
            # soon as we start the prepuller executor just below.
            k_str = str(exc)
        config = configuration_dependency.config
        await context_dependency.initialize(config)
        logger = structlog.get_logger(name=config.safir.logger_name)
        if k_str:
            logger.warning(k_str)

    @app.on_event("shutdown")
    async def shutdown_event() -> None:
        await context_dependency.aclose()
        await http_client_dependency.aclose()

    return app
