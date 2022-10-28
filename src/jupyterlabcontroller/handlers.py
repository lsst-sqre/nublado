"""User-facing routes, as defined in sqr-066 (https://sqr-066.lsst.io)"""
from typing import List

from aiojobs import Scheduler
from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from safir.dependencies.logger import logger_dependency
from safir.metadata import Metadata, get_metadata
from safir.models import ErrorModel
from sse_starlette.sse import EventSourceResponse
from structlog.stdlib import BoundLogger

from .dependencies.config import configuration_dependency
from .dependencies.jobs import scheduler_dependency
from .dependencies.labs import lab_dependency
from .dependencies.token import user_dependency
from .models.index import Index
from .models.v1.domain.config import Config
from .models.v1.external.prepuller import (
    PrepulledImageDisplayList,
    PrepullerStatus,
)
from .models.v1.external.userdata import (
    LabSpecification,
    UserData,
    UserInfo,
    UserMap,
)
from .services.events import user_event_publisher
from .services.form import generate_user_lab_form
from .services.labs import check_for_user, get_active_users
from .storage.lab.create_lab import create_lab_environment
from .storage.lab.delete_lab import delete_lab_environment
from .storage.prepuller.prepuller import get_current_image_and_node_state

# FastAPI routers
external_router = APIRouter()
internal_router = APIRouter()


#
# Event stream handler
#


@external_router.get(
    "/spawner/v1/labs/{username}/events",
    summary="Get Lab event stream for a user's current operation",
)
async def get_user_events(
    username: str,
) -> EventSourceResponse:
    """Requires exec:notebook and valid user token"""
    return EventSourceResponse(user_event_publisher(username))


#
# Form handler
#
@external_router.get(
    "/spawner/v1/lab-form/{username}",
    summary="Get lab form for user",
)
async def get_user_lab_form(
    user: UserInfo = Depends(user_dependency),
    logger: BoundLogger = Depends(logger_dependency),
) -> str:
    """Requires exec:notebook and valid token."""
    return generate_user_lab_form(user)


#
# User routes
#


# Lab Controller API: https://sqr-066.lsst.io/#lab-controller-rest-api


@external_router.get(
    "/spawner/v1/labs",
    response_model=List[str],
    summary="List all users with running labs",
)
async def get_lab_users() -> List[str]:
    """requires admin:jupyterlab"""
    return get_active_users()


@external_router.get(
    "/spawner/v1/labs/{username}",
    response_model=UserData,
    responses={404: {"description": "Lab not found", "model": ErrorModel}},
    summary="Status of user",
)
async def get_userdata(
    username: str,
    labs: UserMap = Depends(lab_dependency),
) -> UserData:
    """Requires admin:jupyterlab"""
    return labs[username]


@external_router.post(
    "/spawner/v1/labs/{username}/create",
    responses={409: {"description": "Lab exists", "model": ErrorModel}},
    response_class=RedirectResponse,
    status_code=303,
    summary="Create user lab",
)
async def post_new_lab(
    lab: LabSpecification,
    user: UserInfo = Depends(user_dependency),
    scheduler: Scheduler = Depends(scheduler_dependency),
    logger: BoundLogger = Depends(logger_dependency),
) -> str:
    """POST body is a LabSpecification.  Requires exec:notebook and valid
    user token."""
    username = user.username
    lab_exists = check_for_user(username)
    if lab_exists:
        raise RuntimeError(f"lab already exists for {username}")
    logger.debug(f"Received creation request for {username}")
    await scheduler.spawn(create_lab_environment(lab))
    return f"/nublado/spawner/v1/labs/{username}"


@external_router.delete(
    "/spawner/v1/labs/{username}",
    summary="Delete user lab",
    responses={404: {"description": "Lab not found", "model": ErrorModel}},
    status_code=202,
)
async def delete_user_lab(
    username: str,
    logger: BoundLogger = Depends(logger_dependency),
    scheduler: Scheduler = Depends(scheduler_dependency),
) -> None:
    """Requires admin:jupyterlab"""
    await scheduler.spawn(delete_lab_environment(username))
    return


@external_router.get(
    "/spawner/v1/user-status",
    responses={404: {"description": "Lab not found", "model": ErrorModel}},
    summary="Get status for user",
)
async def get_user_status(
    user: UserInfo = Depends(user_dependency),
    logger: BoundLogger = Depends(logger_dependency),
    labs: UserMap = Depends(lab_dependency),
) -> UserData:
    """Requires exec:notebook and valid token."""
    return labs[user.username]


#
# Prepuller routes
#

# Prepuller API: https://sqr-066.lsst.io/#rest-api


@external_router.get(
    "/spawner/v1/images",
    summary="Get known images and their names",
)
async def get_images(
    logger: BoundLogger = Depends(logger_dependency),
) -> PrepulledImageDisplayList:
    """Requires admin:notebook"""
    current_state, nodes = await get_current_image_and_node_state()
    return PrepulledImageDisplayList()


@external_router.get(
    "/spawner/v1/prepulls",
    summary="Get status of prepull configurations",
)
async def get_prepulls(
    logger: BoundLogger = Depends(logger_dependency),
) -> PrepullerStatus:
    """Requires admin:notebook"""
    return PrepullerStatus()


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
