"""The main application factory for the jupyterlab-controller service.

Notes
-----
Be aware that, following the normal pattern for FastAPI services, the app is
constructed when this module is loaded and is not deferred until a function is
called.
"""

import os
from importlib.metadata import metadata, version
from typing import Optional

from fastapi import FastAPI
from safir.dependencies.http_client import http_client_dependency
from safir.kubernetes import initialize_kubernetes
from safir.logging import configure_logging, configure_uvicorn_logging
from safir.middleware.x_forwarded import XForwardedMiddleware

from .dependencies.config import configuration_dependency
from .dependencies.docker import docker_client_dependency
from .dependencies.k8s import k8s_api_dependency
from .handlers import external_router, internal_router

__all__ = ["app"]

#
# This is a gross hack for testing.  I hope I can do better.
#

c_path: Optional[str] = os.getenv("JUPYTERLAB_CONTROLLER_CONFIGURATION_PATH")
d_path: Optional[str] = os.getenv("JUPYTERLAB_CONTROLLER_DOCKER_SECRETS_PATH")

if d_path:
    docker_client_dependency.set_secrets_path(d_path)
if c_path:
    configuration_dependency.set_configuration_path(c_path)
config = configuration_dependency.config()

configure_logging(
    profile=config.safir.profile,
    log_level=config.safir.log_level,
    name=config.safir.logger_name,
)
configure_uvicorn_logging(config.safir.log_level)

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


@app.on_event("startup")
async def startup_event() -> None:
    app.add_middleware(XForwardedMiddleware)
    await initialize_kubernetes()


@app.on_event("shutdown")
async def shutdown_event() -> None:
    await k8s_api_dependency.aclose()
    await http_client_dependency.aclose()
