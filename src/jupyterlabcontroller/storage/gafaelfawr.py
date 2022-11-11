from typing import List, Optional

from fastapi import Request
from httpx import AsyncClient

from ..models.v1.external.lab import UserInfo


class GafaelfawrStorageClient:
    def __init__(self, request: Request, http_client: AsyncClient) -> None:
        token = request.headers.get("X-Auth-Request-Token")
        assert token is not None, "No authorization token supplied"
        self.token = token
        assert http_client is not None, "No HTTP client supplied"
        self.http_client = http_client
        self._user: Optional[UserInfo] = None
        self._scopes: List[str] = []

    async def get_user(self) -> UserInfo:
        if self._user is None:
            # It's OK to use a cache here, since the lifespan of this
            # manager is a single request.  If there's more than one
            # get_user() call in its lifespan, something's weird, though.
            # Ask Gafaelfawr for user corresponding to token
            headers = {"Authorization": f"Bearer {self.token}"}
            endpoint = "/auth/ap1/v1/user-info"
            assert self.http_client is not None  # It won't be post-__init__,
            # but mypy can't tell that.
            resp = await self.http_client.get(endpoint, headers=headers)
            obj = resp.json()
            self._user = UserInfo.parse_obj(obj)
        return self._user

    async def get_scopes(self) -> List[str]:
        if not self._scopes:
            headers = {"Authorization": f"Bearer {self.token}"}
            endpoint = "/auth/ap1/v1/token-info"
            assert self.http_client is not None  # It won't be post-__init__
            # but mypy can't tell that.
            resp = await self.http_client.get(endpoint, headers=headers)
            obj = resp.json()
            self._scopes = obj["scopes"]
        return self._scopes

    async def get_token(self) -> str:
        return self.token
