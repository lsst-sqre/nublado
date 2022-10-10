"""Handlers for the app's external root, ``/jupyterlab-controller/``."""

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from safir.dependencies.logger import logger_dependency
from safir.metadata import get_metadata
from structlog.stdlib import BoundLogger
from typing import List

from ..config import config
from ..models import Index, UserData, LabSpecification, Event

__all__ = ["get_index", "external_router"]

external_router = APIRouter()
"""FastAPI router for all external handlers."""


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
        application_name=config.name,
    )
    return Index(metadata=metadata)

@external_router.get(
    "/spawner/v1/labs",
    response_model=List[str],
    summary="List all users with running labs"
)
async def get_lab_users() -> List[str]:
    """requires admin:notebook"""
    return []

@external_router.get(
    "/spawner/v1/labs/{username}",
    response_model=UserData,
    responses={404: {"description": "Lab not found", "model": ErrorModel}},
    summary="Status of user",
)
async def get_userdata(
    username: str,
) -> UserData:
    """Requires admin:jupyterlab"""
    return UserData()

@external_router.post(
    "/spawner/v1/labs/{username}/create",
    responses={409: {"description": "Lab exists", "model": ErrorModel}},
    response_class=RedirectResponse,
    status_code=303,
    summary="Create user lab",
)
async def post_new_lab(
    username: str,
    ) -> Redirect:
    """POST body is a LabSpecification.  Requires exec:notebook and valid
    user token."""
    return "http://localhost"

@external_router.get(
    "/spawner/v1/labs/{username}/events",
    summary="Get Lab event stream for a user's current operation",
)
async def get_user_events(
    username: str,
) -> List[Event]:
    """Requires exec:notebook and valid user token"""
    return []

@external_router.delete(
    "/spawner/v1/labs/{username}",
    responses={404: {"description": "Lab not found", "model": ErrorModel}},
    status_code=202,
)
async def delete_user_lab(
    username:str,
) -> None:
    """Requires admin:notebook"""
    return

@external_router.get(
    "/spawner/v1/lab-form/{username}",
)
async def get_user_lab_form(
    username:str,
    ) -> str:
    """Requires exec:notebook and valid token."""
    return ""

@external_router.get(
    "/spawner/v1/user-status",
    responses={404: {"description": "Lab not found", "model": ErrorModel}},
)
async def get_user_status() -> UserData:
    return UserData()
