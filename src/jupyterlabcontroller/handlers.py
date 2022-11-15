"""User-facing routes, as defined in sqr-066 (https://sqr-066.lsst.io)"""
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from safir.dependencies.logger import logger_dependency
from safir.metadata import Metadata, get_metadata
from safir.models import ErrorModel
from sse_starlette.sse import ServerSentEvent
from structlog.stdlib import BoundLogger

from .config import Config
from .dependencies.config import configuration_dependency
from .dependencies.context import context_dependency
from .dependencies.token import admin_token_dependency, user_token_dependency
from .models.context import Context
from .models.index import Index
from .models.v1.lab import LabSpecification, RunningLabUsers, UserData
from .models.v1.prepuller import DisplayImages, PrepullerStatus
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
    responses={
        403: {"description": "Forbidden", "model": ErrorModel},
    },
    summary="List all users with running labs",
)
async def get_lab_users(
    context: Context = Depends(context_dependency),
    admin_token: str = Depends(admin_token_dependency),
) -> RunningLabUsers:
    """Returns a list of all users with running labs."""
    return get_active_users(context.user_map)


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
    return context.user_map[username]


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
    lab: LabSpecification,
    context: Context = Depends(context_dependency),
    user_token: str = Depends(user_token_dependency),
) -> str:
    """Create a new Lab pod for a given user"""
    lab_manager = LabManager(lab=lab, context=context)
    username = lab_manager.user
    if username == "":
        raise RuntimeError("Cannot create lab without user")
    context.logger.debug(f"Received creation request for {username}")
    await lab_manager.create_lab()
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
    context: Context = Depends(context_dependency),
    admin_token: str = Depends(admin_token_dependency),
) -> None:
    """Stop a running pod."""
    lab_manager = LabManager(lab=LabSpecification(), context=context)
    await lab_manager.delete_lab_environment(username)
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
    if context.user is None:
        raise RuntimeError("Cannot get user status without user")
    return context.user_map[context.user.username]


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
    event_manager = EventManager(
        logger=context.logger, events=context.event_map.get(username)
    )
    # should return EventSourceResponse:
    return event_manager.user_event_publisher(username)


#
# Form handler
#
@external_router.get(
    "/spawner/v1/lab-form/{username}",
    summary="Get lab form for user",
    responses={
        403: {"description": "Forbidden", "model": ErrorModel},
    },
    # FIXME: is there a response_class for 'str' ?
)
async def get_user_lab_form(
    username: str,
    context: Context = Depends(context_dependency),
    user_token: str = Depends(user_token_dependency),
) -> str:
    """Get the lab creation form for a particular user."""
    form_manager = FormManager(context=context)
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
    response_model=DisplayImages,
)
async def get_images(
    context: Context = Depends(context_dependency),
    admin_token: str = Depends(admin_token_dependency),
) -> DisplayImages:
    """Returns known images and their names."""
    prepuller_manager = PrepullerManager(context=context)
    return await prepuller_manager.get_menu_images()


@external_router.get(
    "/spawner/v1/prepulls",
    summary="Get status of prepull configurations",
    responses={
        403: {"description": "Forbidden", "model": ErrorModel},
    },
    response_model=PrepullerStatus,
)
async def get_prepulls(
    context: Context = Depends(context_dependency),
    admin_token: str = Depends(admin_token_dependency),
) -> PrepullerStatus:
    """Returns the list of known images and their names."""
    prepuller_manager = PrepullerManager(context=context)
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
