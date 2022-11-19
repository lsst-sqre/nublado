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
from fastapi import FastAPI
from httpx import AsyncClient
from safir import logging
from safir.dependencies.http_client import http_client_dependency
from safir.kubernetes import initialize_kubernetes
from safir.logging import configure_logging, configure_uvicorn_logging
from safir.middleware.x_forwarded import XForwardedMiddleware

from .dependencies.config import configuration_dependency
from .dependencies.prepull import prepuller_manager_dependency
from .dependencies.storage import (
    docker_storage_dependency,
    k8s_storage_dependency,
)
from .handlers import external_router, internal_router
from .models.domain.storage import StorageClientBundle

__all__ = ["create_app"]


def create_app(
    *,
    config_dir: Optional[str] = None,
    storage_clients: Optional[StorageClientBundle] = None,
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

    if config_dir is not None:
        configuration_dependency.set_filename(f"{config_dir}/config.yaml")
    config = configuration_dependency.config

    configure_logging(
        profile=config.safir.profile,
        log_level=config.safir.log_level,
        name=config.safir.logger_name,
    )
    configure_uvicorn_logging(config.safir.log_level)

    if storage_clients is not None:
        k8s_client = storage_clients.k8s_client
        logger = structlog.get_logger(logging.logger_name)
        http_client = AsyncClient(follow_redirects=True)
        k8s_storage_dependency.set_state(
            k8s_client=k8s_client,
            logger=logger,
        )
        docker_client = storage_clients.docker_client
        docker_storage_dependency.set_state(
            docker_client=docker_client,
            logger=logger,
            config=config,
            http_client=http_client,
        )
        prepuller_manager_dependency.set_state(
            logger=logger,
            k8s_client=k8s_client,
            docker_client=docker_client,
            config=config,
        )

    app = FastAPI(
        title="jupyterlab-controller",
        description=metadata("jupyterlab-controller")["Summary"],
        version=version("jupyterlab-controller"),
        openapi_url=f"/{config.safir.name}/openapi.json",
        docs_url=f"/{config.safir.name}/docs",
        redoc_url=f"/{config.safir.name}/redoc",
    )

    """The main FastAPI application for jupyterlab-controller."""

    # Attach the routers.
    app.include_router(internal_router)
    app.include_router(external_router, prefix=f"/{config.safir.name}")

    # Register lifecycle handlers.
    app.on_event("startup")(startup_event)
    app.on_event("shutdown")(shutdown_event)

    app.add_middleware(XForwardedMiddleware)

    return app


async def startup_event() -> None:
    await initialize_kubernetes()
    await prepuller_manager_dependency.run()


async def shutdown_event() -> None:
    await prepuller_manager_dependency.stop()
    await http_client_dependency.aclose()
