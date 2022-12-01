from typing import List

from httpx import AsyncClient

from jupyterlabcontroller.models.v1.lab import UserInfo
from jupyterlabcontroller.storage.gafaelfawr import GafaelfawrStorageClient

from ..settings import TestObjectFactory, test_object_factory


class MockGafaelfawrStorageClient(GafaelfawrStorageClient):
    def __init__(
        self, token: str, http_client: AsyncClient, test_obj: TestObjectFactory
    ) -> None:
        self.token = token

    async def get_user(self) -> UserInfo:
        if self.token == "token-of-affection":
            return test_object_factory.userinfos[0]
        elif self.token == "token-of-authority":
            return test_object_factory.userinfos[1]
        else:
            raise RuntimeError(f"invalid token '{self.token}'")

    async def get_scopes(self) -> List[str]:
        scopes: List[str] = []
        if self.token == "token-of-affection":
            scopes = ["exec:notebook"]
        elif self.token == "token-of-authority":
            scopes = ["exec:notebook", "admin:jupyterlab"]
        return scopes
