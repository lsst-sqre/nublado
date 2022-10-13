from fastapi import Depends
from safir.dependencies.logger import logger_dependency
from structlog.stdlib import BoundLogger

from .models.userdata import LabSpecification
from .runtime.events import user_events

__all__ = ["create_lab_environment"]


async def create_lab_environment(
    username: str,
    lab: LabSpecification,
    token: str,
    logger: BoundLogger = Depends(logger_dependency),
) -> None:
    # Clear Events for user:
    user_events[username] = []
    namespace = await _create_user_namespace(username)
    await _create_user_lab_objects(namespace, username, lab, token)
    await _create_user_lab_pod(namespace, username, lab)
    # user creation was successful; drop events.
    del user_events[username]
    return


async def _create_user_namespace(username: str) -> str:
    return ""


async def _create_user_lab_objects(
    namespace: str, username: str, lab: LabSpecification, token: str
) -> None:
    return


async def _create_user_lab_pod(
    namespace: str, username: str, lab: LabSpecification
) -> None:
    return
