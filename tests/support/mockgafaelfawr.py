from typing import List

from jupyterlabcontroller.models.v1.lab import UserInfo
from jupyterlabcontroller.storage.gafaelfawr import GafaelfawrStorageClient

from ..settings import TestObjectFactory


class MockGafaelfawrStorageClient(GafaelfawrStorageClient):
    def __init__(self, test_obj: TestObjectFactory) -> None:
        self.test_object_factory = test_obj

    async def get_user(self, token: str) -> UserInfo:
        if token == "token-of-affection":
            return self.test_object_factory.userinfos[0]
        elif token == "token-of-authority":
            return self.test_object_factory.userinfos[1]
        else:
            raise RuntimeError(f"invalid token '{token}'")

    async def get_scopes(self, token: str) -> List[str]:
        scopes: List[str] = []
        if token == "token-of-affection":
            scopes = ["exec:notebook"]
        elif token == "token-of-authority":
            scopes = ["exec:notebook", "admin:jupyterlab"]
        return scopes
