"""
NubladoDependency is an all-in-one dependency, because managing
individual dependencies turned out to be a real pain.  It's designed to
capture the long-term context of a Nublado Lab Controller instance.

It's will work both as a real FastAPI dependency and as a factory to
produce appropriate objects for testing.

It comes with a second class, which is RequestContextDependency.  These
are the things that change on a per-user (which means per-request) basis.
From FastAPI's perspective these are the same--each dependency is per-request.

Each requires that the configuration has been loaded first.

"""

from typing import Optional

from fastapi import Depends, Request
from httpx import AsyncClient
from safir.dependencies.http_client import http_client_dependency
from safir.dependencies.logger import logger_dependency
from structlog.stdlib import BoundLogger

from ..models.v1.domain.config import Config
from ..models.v1.domain.context import ContextContainer, RequestContext
from ..storage.gafaelfawr import GafaelfawrStorageClient
from ..utils import get_user_namespace
from .config import configuration_dependency


class NubladoDependency:
    _container: Optional[ContextContainer] = None

    async def __call__(
        self,
        config: Config = Depends(configuration_dependency),
        http_client: AsyncClient = Depends(http_client_dependency),
        logger: BoundLogger = Depends(logger_dependency),
    ) -> ContextContainer:
        if self._container is None:
            self._container = ContextContainer.initialize(
                config=config, http_client=http_client, logger=logger
            )
        return self._container

    async def aclose(self) -> None:
        if self._container is not None:
            await self._container.aclose()


nublado_dependency = NubladoDependency()


class RequestContextDependency:
    async def __call__(
        self,
        request: Request,
        nublado: ContextContainer = Depends(nublado_dependency),
    ) -> RequestContext:
        client = GafaelfawrStorageClient(
            request=request, http_client=nublado.http_client
        )
        token = await client.get_token()
        user = await client.get_user()
        namespace = get_user_namespace(user.username)
        return RequestContext(
            token=token,
            user=user,
            namespace=namespace,
        )


request_context_dependency = RequestContextDependency()
