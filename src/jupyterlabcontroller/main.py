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

from aiojobs import Scheduler
from fastapi import FastAPI
from safir.dependencies.http_client import http_client_dependency
from safir.kubernetes import initialize_kubernetes
from safir.logging import configure_logging, configure_uvicorn_logging
from safir.middleware.x_forwarded import XForwardedMiddleware

from .dependencies.config import configuration_dependency
from .handlers import external_router, internal_router
from .services.prepuller import PrepullExecutor

__all__ = ["app"]

#
# We need to be able to override the config location for testing and running
# locally, and if we do, we have to set it in an environment variable, because
# we need it to point to the config we would need to initialize the
# app.
#
# If this path is set, we will assume that it contains the path to a directory
# that contains both 'config.yaml' and 'docker_config.json'.
#
modified_cfg_dir: Optional[str] = os.getenv(
    "JUPYTERLAB_CONTROLLER_CONFIGURATION_DIR"
)
if modified_cfg_dir:
    configuration_dependency.set_filename(f"{modified_cfg_dir}/config.yaml")
config = configuration_dependency.config

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

# Create container for prepuller task
prepull_scheduler: Optional[Scheduler] = None
prepull_executor: Optional[PrepullExecutor] = None


@app.on_event("startup")
async def startup_event() -> None:
    app.add_middleware(XForwardedMiddleware)
    await initialize_kubernetes()
    prepull_scheduler = Scheduler(
        close_timeout=config.kubernetes.request_timeout
    )
    prepull_executor = PrepullExecutor(config=config)
    await prepull_scheduler.spawn(prepull_executor.run())


@app.on_event("shutdown")
async def shutdown_event() -> None:
    if prepull_executor is not None:
        await prepull_executor.stop()
    if prepull_scheduler is not None:
        await prepull_scheduler.close()
    await http_client_dependency.aclose()
