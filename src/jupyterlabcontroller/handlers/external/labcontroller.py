"""Handlers for the app's external root, ``/nublado/``."""

from typing import List

from fastapi import Depends, RedirectResponse
from safir.dependencies.logger import logger_dependency
from structlog.stdlib import BoundLogger

from ...models.errormodel import ErrorModel
from ...models.event import Event
from ...models.labspecification import LabSpecification
from ...models.userdata import UserData
from .router import external_router

__all__ = [
    "get_lab_users",
    "get_userdata",
    "post_new_lab",
    "get_user_events",
    "delete_user_lab",
    "get_user_lab_form",
    "get_user_status",
]

# Lab Controller API: https://sqr-066.lsst.io/#lab-controller-rest-api


@external_router.get(
    "/spawner/v1/labs",
    response_model=List[str],
    summary="List all users with running labs",
)
async def get_lab_users(
    logger: BoundLogger = Depends(logger_dependency),
) -> List[str]:
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
    logger: BoundLogger = Depends(logger_dependency),
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
    logger: BoundLogger = Depends(logger_dependency),
) -> RedirectResponse:
    """POST body is a LabSpecification.  Requires exec:notebook and valid
    user token."""
    _ = LabSpecification()
    return "http://localhost"


@external_router.get(
    "/spawner/v1/labs/{username}/events",
    summary="Get Lab event stream for a user's current operation",
)
async def get_user_events(
    username: str,
    logger: BoundLogger = Depends(logger_dependency),
) -> List[Event]:
    """Requires exec:notebook and valid user token"""
    return []


@external_router.delete(
    "/spawner/v1/labs/{username}",
    summary="Delete user lab",
    responses={404: {"description": "Lab not found", "model": ErrorModel}},
    status_code=202,
)
async def delete_user_lab(
    username: str,
    logger: BoundLogger = Depends(logger_dependency),
) -> None:
    """Requires admin:notebook"""
    return


@external_router.get(
    "/spawner/v1/lab-form/{username}",
    summary="Get lab form for user",
)
async def get_user_lab_form(
    username: str,
    logger: BoundLogger = Depends(logger_dependency),
) -> str:
    """Requires exec:notebook and valid token."""
    return ""


@external_router.get(
    "/spawner/v1/user-status",
    responses={404: {"description": "Lab not found", "model": ErrorModel}},
    summary="Get status for user",
)
async def get_user_status(
    logger: BoundLogger = Depends(logger_dependency),
) -> UserData:
    """Requires exec:notebook and valid token."""
    return UserData()
