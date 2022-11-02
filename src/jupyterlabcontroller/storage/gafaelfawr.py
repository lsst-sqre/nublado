from typing import Optional

from fastapi import Depends, Request
from httpx import AsyncClient
from safir.dependencies.http_client import http_client_dependency

from ..models.v1.external.lab import UserInfo


class GafaelfawrStorageClient:
    token: str = ""
    http_client: Optional[AsyncClient] = None
    _user: Optional[UserInfo] = None

    def __init__(
        self,
        request: Request,
        http_client: AsyncClient = Depends(http_client_dependency),
    ) -> None:
        token = request.headers.get("X-Auth-Request-Token")
        self.token = token
        self.http_client = http_client

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

    async def get_token(self) -> str:
        return self.token
