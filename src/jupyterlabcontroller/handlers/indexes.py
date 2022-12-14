"""User-facing routes, as defined in sqr-066 (https://sqr-066.lsst.io)"""
from fastapi import APIRouter, Depends
from safir.dependencies.logger import logger_dependency
from safir.metadata import Metadata, get_metadata
from structlog.stdlib import BoundLogger

from ..config import Configuration
from ..dependencies.config import configuration_dependency
from ..models.index import Index

# FastAPI routers
external_index_router = APIRouter()
internal_index_router = APIRouter()
#
# Index handler
#

"""Handlers for the app's external root, ``/nublado/``."""


@external_index_router.get(
    "/",
    description=(
        "Document the top-level API here. By default it only returns metadata"
        " about the application."
    ),
    response_model=Index,
    response_model_exclude_none=True,
    summary="Application metadata",
)
async def get_index(
    logger: BoundLogger = Depends(logger_dependency),
    config: Configuration = Depends(configuration_dependency),
) -> Index:
    """GET ``/nublado/`` (the app's external root).

    Customize this handler to return whatever the top-level resource of your
    application should return. For example, consider listing key API URLs.
    When doing so, also change or customize the response model in
    `jupyterlabcontroller.models.Index`.

    By convention, the root of the external API includes a field called
    ``metadata`` that provides the same Safir-generated metadata as the
    internal root endpoint.
    """
    # There is no need to log simple requests since uvicorn will do this
    # automatically, but this is included as an example of how to use the
    # logger for more complex logging.
    logger.info("Request for application metadata")

    metadata = get_metadata(
        package_name="jupyterlab-controller",
        application_name=config.safir.name,
    )
    return Index(metadata=metadata)


#
# Internal handler
#

"""Internal HTTP handlers that serve relative to the root path, ``/``.

These handlers aren't externally visible since the app is available at
a path, ``/nublado``. See the preceding part of this file for external
endpoint handlers.

These handlers should be used for monitoring, health checks, internal status,
or other information that should not be visible outside the Kubernetes cluster.
"""


@internal_index_router.get(
    "/",
    description=(
        "Return metadata about the running application. Can also be used as"
        " a health check. This route is not exposed outside the cluster and"
        " therefore cannot be used by external clients."
    ),
    include_in_schema=False,
    response_model=Metadata,
    response_model_exclude_none=True,
    summary="Application metadata",
)
async def get_internal_index(
    config: Configuration = Depends(configuration_dependency),
) -> Metadata:
    """GET ``/`` (the app's internal root).

    By convention, this endpoint returns only the application's metadata.
    """
    return get_metadata(
        package_name="jupyterlab-controller",
        application_name=config.safir.name,
    )
