from typing import Any, Dict, List, cast

from httpx import AsyncClient

from ..models.domain.storage import GafaelfawrCache
from ..models.v1.lab import UserInfo


class GafaelfawrStorageClient:
    def __init__(self, http_client: AsyncClient) -> None:
        self.http_client = http_client
        self._api_url = "/auth/api/v1"
        self._cache: Dict[str, GafaelfawrCache]

    async def _fetch(self, endpoint: str, token: str) -> Any:
        url = f"{self._api_url}/{endpoint}"
        headers = {"Authorization": f"bearer {token}"}
        resp = await self.http_client.get(url, headers=headers)
        return resp.json()

    async def get_user(self, token: str) -> UserInfo:
        # defaultdict did not work as I expected.
        if self._cache.get(token) is None:
            self._cache[token] = GafaelfawrCache()
        if self._cache[token].user is None:
            obj = await self._fetch("user-info", token)
            self._cache[token].user = UserInfo.parse_obj(obj)
        return cast(UserInfo, self._cache[token].user)

    async def get_scopes(self, token: str) -> List[str]:
        if self._cache.get(token) is None:
            self._cache[token] = GafaelfawrCache()
        if self._cache[token].scopes is None:
            obj = await self._fetch("token-info", token)
            self._cache[token].scopes = cast(List[str], obj["scopes"])
        return cast(List[str], self._cache[token].scopes)
