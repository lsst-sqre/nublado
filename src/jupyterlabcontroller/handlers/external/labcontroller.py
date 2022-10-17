"""Handlers for the app's external root, ``/nublado/``."""

import asyncio
from typing import List

from fastapi import Depends, Request
from fastapi.responses import RedirectResponse
from safir.dependencies.logger import logger_dependency
from safir.models import ErrorModel
from structlog.stdlib import BoundLogger

from ...kubernetes.create_lab import create_lab_environment
from ...kubernetes.delete_lab import delete_lab_environment
from ...models.userdata import LabSpecification, UserData, UserInfo
from ...runtime.labs import check_for_user, get_active_users, labs
from ...runtime.tasks import manage_task
from ...runtime.token import get_user_from_token
from .router import external_router

__all__ = [
    "get_lab_users",
    "get_userdata",
    "post_new_lab",
    "delete_user_lab",
    "get_user_status",
]

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
async def get_userdata(username: str) -> UserData:
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
    request: Request,
    lab: LabSpecification,
    user: UserInfo,
    logger: BoundLogger = Depends(logger_dependency),
) -> str:
    """POST body is a LabSpecification.  Requires exec:notebook and valid
    user token."""
    token = request.headers.get("X-Auth-Request-Token")
    user = await get_user_from_token(token)
    username = user.username
    lab_exists = check_for_user(username)
    if lab_exists:
        raise RuntimeError(f"lab already exists for {username}")
    logger.debug(f"Received creation request for {username}")
    task = asyncio.create_task(create_lab_environment(user, lab, token))
    manage_task(task)
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
) -> None:
    """Requires admin:jupyterlab"""
    task = asyncio.create_task(delete_lab_environment(username))
    manage_task(task)
    return


@external_router.get(
    "/spawner/v1/user-status",
    responses={404: {"description": "Lab not found", "model": ErrorModel}},
    summary="Get status for user",
)
async def get_user_status(
    request: Request,
    logger: BoundLogger = Depends(logger_dependency),
) -> UserData:
    """Requires exec:notebook and valid token."""
    token = request.headers.get("X-Auth-Request-Token")
    user = await get_user_from_token(token)
    return labs[user.username]
