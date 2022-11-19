"""
ContextDependency is an all-in-one dependency, because managing
individual dependencies turned out to be a real pain.  It's designed to
capture the context of any request.  It requires that a Configuration has been
loaded before it can be instantiated.
"""

from fastapi import Depends, Request
from httpx import AsyncClient
from safir.dependencies.http_client import http_client_dependency
from safir.dependencies.logger import logger_dependency
from structlog.stdlib import BoundLogger

from ..config import Configuration
from ..models.context import Context
from ..storage.docker import DockerStorageClient
from ..storage.k8s import K8sStorageClient
from .config import configuration_dependency
from .storage import docker_storage_dependency, k8s_storage_dependency


class ContextDependency:
    async def __call__(
        self,
        request: Request,
        config: Configuration = Depends(configuration_dependency),
        http_client: AsyncClient = Depends(http_client_dependency),
        logger: BoundLogger = Depends(logger_dependency),
        k8s_client: K8sStorageClient = Depends(k8s_storage_dependency),
        docker_client: DockerStorageClient = Depends(
            docker_storage_dependency
        ),
    ) -> Context:
        context: Context = Context.initialize(
            config=config,
            http_client=http_client,
            logger=logger,
            k8s_client=k8s_client,
            docker_client=docker_client,
        )
        await context.patch_with_request(request)
        return context


context_dependency = ContextDependency()
