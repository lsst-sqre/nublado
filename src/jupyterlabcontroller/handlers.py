"""User-facing routes, as defined in sqr-066 (https://sqr-066.lsst.io)"""
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from safir.dependencies.logger import logger_dependency
from safir.metadata import Metadata, get_metadata
from safir.models import ErrorModel
from sse_starlette.sse import ServerSentEvent
from structlog.stdlib import BoundLogger

from .dependencies.config import configuration_dependency
from .dependencies.nublado import (
    ContextContainer,
    RequestContext,
    nublado_dependency,
    request_context_dependency,
)
from .models.index import Index
from .models.v1.domain.config import Config
from .models.v1.external.lab import LabSpecification, RunningLabUsers, UserData
from .models.v1.external.prepuller import DisplayImages, PrepullerStatus
from .services.events import EventManager
from .services.form import FormManager
from .services.lab import LabManager
from .services.prepuller import PrepullerManager
from .utils import get_active_users

# from sse_starlette.sse import EventSourceResponse

# FastAPI routers
external_router = APIRouter()
internal_router = APIRouter()


#
# User routes
#


# Lab Controller API: https://sqr-066.lsst.io/#lab-controller-rest-api


@external_router.get(
    "/spawner/v1/labs",
    response_model=RunningLabUsers,
    summary="List all users with running labs",
)
async def get_lab_users(
    nublado: ContextContainer = Depends(nublado_dependency),
) -> RunningLabUsers:
    """requires admin:jupyterlab"""
    return get_active_users(nublado.user_map)


@external_router.get(
    "/spawner/v1/labs/{username}",
    response_model=UserData,
    responses={404: {"description": "Lab not found", "model": ErrorModel}},
    summary="Status of user",
)
async def get_userdata(
    username: str,
    nublado: ContextContainer = Depends(nublado_dependency),
    context: RequestContext = Depends(request_context_dependency),
) -> UserData:
    """Requires admin:jupyterlab"""
    return nublado.user_map[username]


@external_router.post(
    "/spawner/v1/labs/{username}/create",
    responses={409: {"description": "Lab exists", "model": ErrorModel}},
    response_class=RedirectResponse,
    status_code=303,
    summary="Create user lab",
)
async def post_new_lab(
    lab: LabSpecification,
    nublado: ContextContainer = Depends(nublado_dependency),
    context: RequestContext = Depends(request_context_dependency),
) -> str:
    """POST body is a LabSpecification.  Requires exec:notebook and valid
    user token."""
    lab_manager = LabManager(lab=lab, nublado=nublado, context=context)
    username = context.user.username
    nublado.logger.debug(f"Received creation request for {username}")
    await lab_manager.create_lab()
    return f"/nublado/spawner/v1/labs/{username}"


@external_router.delete(
    "/spawner/v1/labs/{username}",
    summary="Delete user lab",
    responses={404: {"description": "Lab not found", "model": ErrorModel}},
    status_code=202,
)
async def delete_user_lab(
    username: str,
    lab: LabSpecification,
    nublado: ContextContainer = Depends(nublado_dependency),
    context: RequestContext = Depends(request_context_dependency),
) -> None:
    """Requires admin:jupyterlab"""
    lab_manager = LabManager(lab=lab, nublado=nublado, context=context)
    await lab_manager.delete_lab_environment(username)
    return


@external_router.get(
    "/spawner/v1/user-status",
    responses={404: {"description": "Lab not found", "model": ErrorModel}},
    summary="Get status for user",
)
async def get_user_status(
    nublado: ContextContainer = Depends(nublado_dependency),
    context: RequestContext = Depends(request_context_dependency),
) -> UserData:
    """Requires exec:notebook and valid token."""
    return nublado.user_map[context.user.username]


#
# Event stream handler
#


@external_router.get(
    "/spawner/v1/labs/{username}/events",
    summary="Get Lab event stream for a user's current operation",
)
async def get_user_events(
    username: str,
    nublado: ContextContainer = Depends(nublado_dependency),
) -> AsyncGenerator[ServerSentEvent, None]:
    """Requires exec:notebook and valid user token"""
    event_manager = EventManager(
        logger=nublado.logger, events=nublado.event_map
    )
    # should return EventSourceResponse:
    return event_manager.user_event_publisher(username)


#
# Form handler
#
@external_router.get(
    "/spawner/v1/lab-form/{username}",
    summary="Get lab form for user",
)
async def get_user_lab_form(
    username: str,
    nublado: ContextContainer = Depends(nublado_dependency),
    context: RequestContext = Depends(request_context_dependency),
) -> str:
    """Requires exec:notebook and valid token."""
    form_manager = FormManager(nublado=nublado, context=context)
    return await form_manager.generate_user_lab_form()


#
# Prepuller routes
#

# Prepuller API: https://sqr-066.lsst.io/#rest-api


@external_router.get(
    "/spawner/v1/images",
    summary="Get known images and their names",
)
async def get_images(
    nublado: ContextContainer = Depends(nublado_dependency),
    context: RequestContext = Depends(request_context_dependency),
) -> DisplayImages:
    """Requires admin:notebook"""
    prepuller_manager = PrepullerManager(nublado=nublado, context=context)
    return await prepuller_manager.get_menu_images()


@external_router.get(
    "/spawner/v1/prepulls",
    summary="Get status of prepull configurations",
)
async def get_prepulls(
    nublado: ContextContainer = Depends(nublado_dependency),
    context: RequestContext = Depends(request_context_dependency),
) -> PrepullerStatus:
    """Requires admin:notebook"""
    prepuller_manager = PrepullerManager(nublado=nublado, context=context)
    return await prepuller_manager.get_prepulls()


#
# Index handler
#

"""Handlers for the app's external root, ``/nublado/``."""


@external_router.get(
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
    config: Config = Depends(configuration_dependency),
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


@internal_router.get(
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
    config: Config = Depends(configuration_dependency),
) -> Metadata:
    """GET ``/`` (the app's internal root).

    By convention, this endpoint returns only the application's metadata.
    """
    return get_metadata(
        package_name="jupyterlab-controller",
        application_name=config.safir.name,
    )
