import asyncio

from fastapi import Depends
from kubernetes_asyncio.client import api_client
from kubernetes_asyncio.client.rest import ApiException
from safir.dependencies.logger import logger_dependency
from structlog.stdlib import BoundLogger

from ...config import config
from ...dependencies.k8s_corev1_api import corev1_api_dependency
from ...runtime.labs import labs
from ...runtime.namespace import get_user_namespace

__all__ = ["delete_lab_environment", "delete_namespace"]


async def delete_lab_environment(
    username: str,
    logger: BoundLogger = Depends(logger_dependency),
) -> None:
    # Clear Events for user:
    labs[username].events = []
    labs[username].status = "terminating"
    ns = get_user_namespace(username)
    try:
        await delete_namespace(ns)
    except Exception as e:
        logger.error(f"Could not delete lab environment: {e}")
        labs[username].status = "failed"
        raise
    del labs[username]


async def delete_namespace(
    namespace: str, api: api_client = Depends(corev1_api_dependency)
) -> None:
    """Delete the namespace with name ``namespace``.  If it doesn't exist,
    that's OK.

    Exposed because create_lab may use it if the user namespace exists but
    we don't have a lab record.
    """
    try:
        await asyncio.wait_for(
            api.delete_namespace(namespace), config.k8s_request_timeout
        )
    except ApiException as e:
        if e.status != 404:
            raise
