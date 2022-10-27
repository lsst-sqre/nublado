import asyncio
from collections import deque

from fastapi import Depends
from kubernetes_asyncio.client import CoreV1Api
from kubernetes_asyncio.client.rest import ApiException
from safir.dependencies.logger import logger_dependency
from structlog.stdlib import BoundLogger

from ....dependencies.namespace import namespace_dependency
from ...config import config
from ...dependencies.k8s import k8s_corev1api_dependency
from ...dependencies.labs import lab_dependency
from ...models.v1.external.userdata import UserMap


async def delete_lab_environment(
    username: str,
    logger: BoundLogger = Depends(logger_dependency),
    labs: UserMap = Depends(lab_dependency),
) -> None:
    # Clear Events for user:
    labs[username].events = deque()
    labs[username].status = "terminating"
    try:
        await delete_namespace()
    except Exception as e:
        logger.error(f"Could not delete lab environment: {e}")
        labs[username].status = "failed"
        raise
    del labs[username]


async def delete_namespace(
    namespace: str = Depends(namespace_dependency),
    api: CoreV1Api = Depends(k8s_corev1api_dependency),
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
