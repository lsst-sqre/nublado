"""The main application factory for the jupyterlab-controller service."""

from importlib.metadata import metadata, version

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from safir.dependencies.http_client import http_client_dependency
from safir.kubernetes import initialize_kubernetes
from safir.logging import configure_logging, configure_uvicorn_logging
from safir.middleware.x_forwarded import XForwardedMiddleware

from .dependencies.config import configuration_dependency
from .dependencies.context import context_dependency
from .exceptions import ValidationError
from .handlers import form, index, labs, prepuller, user_status

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
        openapi_url=f"/{config.safir.path_prefix}/openapi.json",
        docs_url=f"{config.safir.path_prefix}/docs",
        redoc_url=f"{config.safir.path_prefix}/redoc",
    )

    # Attach the routers.
    app.include_router(index.internal_router)
    app.include_router(index.external_router, prefix=config.safir.path_prefix)
    app.include_router(form.router, prefix=config.safir.path_prefix)
    app.include_router(labs.router, prefix=config.safir.path_prefix)
    app.include_router(prepuller.router, prefix=config.safir.path_prefix)
    app.include_router(user_status.router, prefix=config.safir.path_prefix)

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

    @app.exception_handler(ValidationError)
    async def validation_handler(
        request: Request, exc: ValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code, content={"detail": [exc.to_dict()]}
        )

    return app
