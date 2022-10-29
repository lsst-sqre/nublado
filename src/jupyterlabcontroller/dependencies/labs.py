from typing import Optional

from fastapi import Depends
from kubernetes_asyncio.client import ApiClient
from safir.dependencies.logger import logger_dependency
from structlog.stdlib import BoundLogger

from ..models.v1.domain.config import Config
from ..models.v1.domain.labs import LabMap
from ..models.v1.external.userdata import UserInfo
from ..storage.lab import LabClient
from .config import configuration_dependency
from .k8s import k8s_api_dependency
from .namespace import namespace_dependency
from .token import token_dependency, user_dependency


class UserLabsDependency:
    def __call__(self) -> LabMap:
        labs: LabMap = {}
        return labs


user_labs_dependency = UserLabsDependency()


class LabClientDependency:
    _client: Optional[LabClient] = None

    async def __call__(
        self,
        user: UserInfo = Depends(user_dependency),
        token: str = Depends(token_dependency),
        logger: BoundLogger = Depends(logger_dependency),
        labs: LabMap = Depends(user_labs_dependency),
        k8s_api: ApiClient = Depends(k8s_api_dependency),
        namespace: str = Depends(namespace_dependency),
        config: Config = Depends(configuration_dependency),
    ) -> LabClient:
        if self._client is None:
            self.client(
                user=user,
                token=token,
                logger=logger,
                labs=labs,
                k8s_api=k8s_api,
                namespace=namespace,
                config=config,
            )
        assert self._client is not None  # Thanks, mypy
        return self._client

    def client(
        self,
        user: UserInfo,
        token: str,
        logger: BoundLogger,
        labs: LabMap,
        k8s_api: ApiClient,
        namespace: str,
        config: Config,
    ) -> None:
        self._client = LabClient(
            user=user,
            token=token,
            logger=logger,
            labs=labs,
            k8s_api=k8s_api,
            namespace=namespace,
            config=config,
        )


lab_client_dependency = LabClientDependency()
