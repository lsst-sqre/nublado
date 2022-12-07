"""User-facing routes, as defined in sqr-066 (https://sqr-066.lsst.io)"""
from collections.abc import AsyncGenerator
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from safir.dependencies.logger import logger_dependency
from safir.metadata import Metadata, get_metadata
from safir.models import ErrorModel
from sse_starlette.sse import ServerSentEvent
from structlog.stdlib import BoundLogger

from .config import Configuration
from .dependencies.config import configuration_dependency
from .dependencies.context import context_dependency
from .dependencies.prepull import prepuller_arbitrator_dependency
from .dependencies.token import admin_token_dependency, user_token_dependency
from .models.context import Context
from .models.index import Index
from .models.v1.lab import LabSpecification, UserData
from .models.v1.prepuller import PrepullerStatus, SpawnerImages
from .services.prepuller.arbitrator import PrepullerArbitrator

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
    responses={
        403: {"description": "Forbidden", "model": ErrorModel},
    },
    summary="List all users with running labs",
)
async def get_lab_users(
    context: Context = Depends(context_dependency),
    admin_token: str = Depends(admin_token_dependency),
) -> List[str]:
    """Returns a list of all users with running labs."""
    return await context.user_map.running()


@external_router.get(
    "/spawner/v1/labs/{username}",
    response_model=UserData,
    responses={
        404: {"description": "Lab not found", "model": ErrorModel},
        403: {"description": "Forbidden", "model": ErrorModel},
    },
    summary="Status of user",
)
async def get_userdata(
    username: str,
    context: Context = Depends(context_dependency),
    admin_token: str = Depends(admin_token_dependency),
) -> UserData:
    """Returns status of the lab pod for the given user."""
    userdata = context.user_map.get(username)
    if userdata is None:
        raise HTTPException(status_code=404, detail="Not found")
    return userdata


@external_router.post(
    "/spawner/v1/labs/{username}/create",
    responses={
        409: {"description": "Lab exists", "model": ErrorModel},
        403: {"description": "Forbidden", "model": ErrorModel},
    },
    response_class=RedirectResponse,
    status_code=303,
    summary="Create user lab",
)
async def post_new_lab(
    username: str,
    lab: LabSpecification,
    context: Context = Depends(context_dependency),
    user_token: str = Depends(user_token_dependency),
    logger: BoundLogger = Depends(logger_dependency),
) -> str:
    """Create a new Lab pod for a given user"""
    user = await context.get_user()
    token_username = user.username
    if token_username != username:
        raise HTTPException(status_code=403, detail="Forbidden")
    lab_manager = context.lab_manager
    context.logger.debug(f"Received creation request for {username}")
    await lab_manager.create_lab(token=user_token, lab=lab)
    return f"/context/spawner/v1/labs/{username}"


@external_router.delete(
    "/spawner/v1/labs/{username}",
    summary="Delete user lab",
    responses={
        404: {"description": "Lab not found", "model": ErrorModel},
        403: {"description": "Forbidden", "model": ErrorModel},
    },
    status_code=202,
)
async def delete_user_lab(
    username: str,
    logger: BoundLogger = Depends(logger_dependency),
    context: Context = Depends(context_dependency),
    admin_token: str = Depends(admin_token_dependency),
) -> None:
    """Stop a running pod."""
    lab_manager = context.lab_manager
    await lab_manager.delete_lab(username)
    return


@external_router.get(
    "/spawner/v1/user-status",
    responses={
        404: {"description": "Lab not found", "model": ErrorModel},
        403: {"description": "Forbidden", "model": ErrorModel},
    },
    summary="Get status for user",
    response_model=UserData,
)
async def get_user_status(
    context: Context = Depends(context_dependency),
    admin_token: str = Depends(admin_token_dependency),
) -> UserData:
    """Get the pod status for the authenticating user."""
    user = await context.get_user()
    if user is None:
        raise RuntimeError("Cannot get user status without user")
    userdata = context.user_map.get(user.username)
    if userdata is None:
        raise HTTPException(status_code=404, detail="Not found")
    return userdata


#
# Event stream handler
#


@external_router.get(
    "/spawner/v1/labs/{username}/events",
    summary="Get Lab event stream for a user's current operation",
    responses={
        403: {"description": "Forbidden", "model": ErrorModel},
    },
    # FIXME: Not at all sure how to do response model/class for this
)
async def get_user_events(
    username: str,
    context: Context = Depends(context_dependency),
    user_token: str = Depends(user_token_dependency),
) -> AsyncGenerator[ServerSentEvent, None]:
    """Returns the events for the lab of the given user"""
    event_manager = context.event_manager
    # should return EventSourceResponse:
    return event_manager.publish(username)


#
# Form handler
#
@external_router.get(
    "/spawner/v1/lab-form/{username}",
    summary="Get lab form for user",
    responses={
        403: {"description": "Forbidden", "model": ErrorModel},
    },
)
async def get_user_lab_form(
    username: str,
    context: Context = Depends(context_dependency),
    user_token: str = Depends(user_token_dependency),
    logger: BoundLogger = Depends(logger_dependency),
    prepuller_arbitrator: PrepullerArbitrator = Depends(
        prepuller_arbitrator_dependency
    ),
) -> str:
    """Get the lab creation form for a particular user."""
    form_manager = context.form_manager
    return await form_manager.generate_user_lab_form()


#
# Prepuller routes
#

# Prepuller API: https://sqr-066.lsst.io/#rest-api


@external_router.get(
    "/spawner/v1/images",
    summary="Get known images and their names",
    responses={
        403: {"description": "Forbidden", "model": ErrorModel},
    },
    response_model=SpawnerImages,
)
async def get_images(
    context: Context = Depends(context_dependency),
    admin_token: str = Depends(admin_token_dependency),
    prepuller_arbitrator: PrepullerArbitrator = Depends(
        prepuller_arbitrator_dependency
    ),
) -> SpawnerImages:
    """Returns known images and their names."""
    return prepuller_arbitrator.get_spawner_images()


@external_router.get(
    "/spawner/v1/prepulls",
    summary="Get status of prepull configurations",
    responses={
        403: {"description": "Forbidden", "model": ErrorModel},
    },
    response_model=PrepullerStatus,
)
async def get_prepulls(
    admin_token: str = Depends(admin_token_dependency),
    prepuller_arbitrator: PrepullerArbitrator = Depends(
        prepuller_arbitrator_dependency
    ),
) -> PrepullerStatus:
    """Returns the list of known images and their names."""
    return prepuller_arbitrator.get_prepulls()


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
    config: Configuration = Depends(configuration_dependency),
) -> Metadata:
    """GET ``/`` (the app's internal root).

    By convention, this endpoint returns only the application's metadata.
    """
    return get_metadata(
        package_name="jupyterlab-controller",
        application_name=config.safir.name,
    )
