"""The main application factory for the jupyterlab-controller service."""

from importlib.metadata import metadata, version

from fastapi import FastAPI
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
        await initialize_kubernetes()
        config = configuration_dependency.config
        await context_dependency.initialize(config)

    @app.on_event("shutdown")
    async def shutdown_event() -> None:
        await context_dependency.aclose()
        await http_client_dependency.aclose()

    return app
