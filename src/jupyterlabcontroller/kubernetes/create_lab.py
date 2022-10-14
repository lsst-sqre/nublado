import asyncio

from fastapi import Depends
from kubernetes_asyncio.client import api_client
from kubernetes_asyncio.client.models import V1Namespace
from kubernetes_asyncio.client.rest import ApiException
from safir.dependencies.logger import logger_dependency
from structlog.stdlib import BoundLogger

from ..models.userdata import LabSpecification
from ..runtime.events import user_events
from ..runtime.namespace import get_user_namespace
from .client import shared_client
from .std_metadata import get_std_metadata

__all__ = ["create_lab_environment"]


async def create_lab_environment(
    username: str,
    lab: LabSpecification,
    token: str,
    logger: BoundLogger = Depends(logger_dependency),
) -> None:
    # Get API
    api = shared_client("CoreV1Api")
    # Clear Events for user:
    user_events[username] = []
    namespace = await _create_user_namespace(api, username)
    await _create_user_lab_objects(api, namespace, username, lab, token)
    await _create_user_lab_pod(api, namespace, username, lab)
    # user creation was successful; drop events.
    del user_events[username]
    return


async def _create_user_namespace(
    api: api_client,
    username: str,
    logger: BoundLogger = Depends(logger_dependency),
) -> str:
    ns_name = get_user_namespace(username)
    try:
        await asyncio.wait_for(
            api.create_namespace(
                V1Namespace(metadata=get_std_metadata(name=ns_name))
            ),
            10,  # replace with better timeout
        )
    except ApiException as e:
        if e.status == 409:
            logger.exception(f"Namespace {ns_name} already exists")
            # ... delete it
        else:
            logger.exception(f"Failed to create namespace {ns_name}: {e}")
            raise
    return ns_name


async def _create_user_lab_objects(
    api: api_client,
    namespace: str,
    username: str,
    lab: LabSpecification,
    token: str,
) -> None:
    return


async def _create_user_lab_pod(
    api: api_client, namespace: str, username: str, lab: LabSpecification
) -> None:
    return
