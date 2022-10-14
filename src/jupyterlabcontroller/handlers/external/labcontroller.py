"""Handlers for the app's external root, ``/nublado/``."""

import asyncio
from typing import List, Set

from fastapi import Depends, Request
from fastapi.responses import RedirectResponse
from safir.dependencies.logger import logger_dependency
from safir.models import ErrorModel
from structlog.stdlib import BoundLogger

from ...kubernetes.create_lab import create_lab_environment
from ...models.userdata import LabSpecification, UserData
from ...runtime.labs import check_for_user, get_active_users, labs
from .events import user_events
from .router import external_router

__all__ = [
    "get_lab_users",
    "get_userdata",
    "post_new_lab",
    "delete_user_lab",
    "get_user_lab_form",
    "get_user_status",
]

# Lab Controller API: https://sqr-066.lsst.io/#lab-controller-rest-api

creation_tasks: Set[asyncio.Task] = set()
deletion_tasks: Set[asyncio.Task] = set()


@external_router.get(
    "/spawner/v1/labs",
    response_model=List[str],
    summary="List all users with running labs",
)
async def get_lab_users() -> List[str]:
    """requires admin:notebook"""
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
    username: str,
    request: Request,
    lab: LabSpecification,
    logger: BoundLogger = Depends(logger_dependency),
) -> str:
    """POST body is a LabSpecification.  Requires exec:notebook and valid
    user token."""
    token = request.headers.get("X-Auth-Request-Token")
    task = asyncio.create_task(create_lab_environment(username, lab, token))
    logger.debug(f"Received creation request for {username}")
    lab_exists = await check_for_user(username)
    if lab_exists:
        raise RuntimeError(f"lab already exists for {username}")
    creation_tasks.add(task)
    task.add_done_callback(creation_tasks.discard)
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
    """Requires admin:notebook"""
    task = asyncio.create_task(_schedule_lab_deletion(username))
    deletion_tasks.add(task)
    task.add_done_callback(deletion_tasks.discard)
    return


async def _schedule_lab_deletion(username: str) -> None:
    user_events[username] = []
    await _delete_user_lab_pod(username)
    await _delete_user_lab_objects(username)
    await _delete_user_lab_namespace(username)
    # user creation was successful; drop events.
    del user_events[username]
    return


async def _delete_user_lab_pod(username: str) -> None:
    pass


async def _delete_user_lab_objects(username: str) -> None:
    pass


async def _delete_user_lab_namespace(username: str) -> None:
    pass


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
    request: Request,
    logger: BoundLogger = Depends(logger_dependency),
) -> UserData:
    """Requires exec:notebook and valid token."""
    token = request.headers.get("X-Auth-Request-Token")
    _ = token
    return UserData()
