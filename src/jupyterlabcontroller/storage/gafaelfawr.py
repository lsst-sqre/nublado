from typing import Any, Dict, cast

from httpx import AsyncClient

from ..config import Configuration
from ..models.domain.storage import GafaelfawrCache
from ..models.v1.lab import UserInfo


class GafaelfawrStorageClient:
    def __init__(
        self, http_client: AsyncClient, config: Configuration
    ) -> None:
        self.http_client = http_client
        self._api_url = f"{config.base_url}/auth/api/v1"
        self._cache: Dict[str, GafaelfawrCache] = dict()

    async def _fetch(self, endpoint: str, token: str) -> Any:
        url = f"{self._api_url}/{endpoint}"
        headers = {"Authorization": f"bearer {token}"}
        resp = await self.http_client.get(url, headers=headers)
        j = resp.json()
        return j

    async def get_user(self, token: str) -> UserInfo:
        # defaultdict did not work as I expected.
        if self._cache.get(token) is None:
            self._cache[token] = GafaelfawrCache()
        if self._cache[token].user is None:
            obj = await self._fetch("user-info", token)
            self._cache[token].user = UserInfo.parse_obj(obj)
        return cast(UserInfo, self._cache[token].user)
