"""The main application factory for the jupyterlab-controller service.

Notes
-----
Be aware that, following the normal pattern for FastAPI services, the app is
constructed when this module is loaded and is not deferred until a function is
called.
"""

from importlib.metadata import metadata, version

from fastapi import FastAPI
from handlers import external_router, internal_router
from safir.dependencies.http_client import http_client_dependency
from safir.kubernetes import initialize_kubernetes
from safir.logging import configure_logging, configure_uvicorn_logging
from safir.middleware.x_forwarded import XForwardedMiddleware

from .config import config
from .dependencies.k8s import k8s_api_dependency

__all__ = ["app"]


configure_logging(
    profile=config.profile,
    log_level=config.log_level,
    name=config.logger_name,
)
configure_uvicorn_logging(config.log_level)

app = FastAPI(
    title="jupyterlab-controller",
    description=metadata("jupyterlab-controller")["Summary"],
    version=version("jupyterlab-controller"),
    openapi_url=f"/{config.name}/openapi.json",
    docs_url=f"/{config.name}/docs",
    redoc_url=f"/{config.name}/redoc",
)
"""The main FastAPI application for jupyterlab-controller."""

# Attach the routers.
app.include_router(internal_router)
app.include_router(external_router, prefix=f"/{config.name}")


@app.on_event("startup")
async def startup_event() -> None:
    app.add_middleware(XForwardedMiddleware)
    await initialize_kubernetes()


@app.on_event("shutdown")
async def shutdown_event() -> None:
    await k8s_api_dependency.aclose()
    await http_client_dependency.aclose()
