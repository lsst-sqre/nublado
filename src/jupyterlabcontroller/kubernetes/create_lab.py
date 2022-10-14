import asyncio

from client import shared_client
from escape import escape
from fastapi import Depends
from kubernetes_asyncio.client import api_client
from kubernetes_asyncio.client.models import V1Namespace, V1ObjectMeta
from kubernetes_asyncio.client.rest import ApiException
from safir.dependencies.logger import logger_dependency
from structlog.stdlib import BoundLogger

from .models.userdata import LabSpecification
from .runtime.events import user_events
from .runtime.namespace import get_namespace_prefix
from .runtime.std import std_annotations, std_labels

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
    ns_name = f"{get_namespace_prefix()}-{escape(username)}"
    ns_md = V1ObjectMeta(
        name=ns_name, labels=std_labels(), annotations=std_annotations()
    )
    try:
        await asyncio.wait_for(
            api.create_namespace(
                V1Namespace(metadata=ns_md), 10  # replace with better timeout
            )
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
