from typing import Any, List, Optional

from httpx import AsyncClient

from ..models.v1.lab import UserInfo


class GafaelfawrStorageClient:
    def __init__(self, token: str, http_client: AsyncClient) -> None:
        self.token = token
        self.http_client = http_client
        self._user: Optional[UserInfo] = None
        self._scopes: List[str] = list()
        self._headers = {"Authorization": f"Bearer {token}"}
        self._api_url = "/auth/api/v1"

    async def _fetch(self, endpoint: str) -> Any:
        resp = await self.http_client.get(
            f"{self._api_url}/{endpoint}", headers=self._headers
        )
        return resp.json()

    async def get_user(self) -> UserInfo:
        if self._user is None:
            # It's OK to use a cache here, since the lifespan of this
            # manager is a single request.  If there's more than one
            # get_user() call in its lifespan, something's weird, though.
            # Ask Gafaelfawr for user corresponding to token
            obj = await self._fetch("user-info")
            self._user = UserInfo.parse_obj(obj)
        return self._user

    async def get_scopes(self) -> List[str]:
        if not self._scopes:
            obj = await self._fetch("token-info")
            self._scopes = obj["scopes"]
        return self._scopes

    async def get_token(self) -> str:
        return self.token
