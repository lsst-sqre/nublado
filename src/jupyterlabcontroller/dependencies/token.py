from fastapi import Depends, Request
from httpx import AsyncClient
from safir.dependencies.http_client import http_client_dependency

from ..models.v1.external.userdata import UserInfo


class TokenDependency:
    """Gets the token from the request."""

    async def __call__(
        self,
        request: Request,
    ) -> str:
        token: str = request.headers.get("X-Auth-Request-Token")
        return token


token_dependency = TokenDependency()


class UserDependency:
    """Takes the token and queries Gafaelfawr for the corresponding user
    info"""

    async def __call__(
        self,
        client: AsyncClient = Depends(http_client_dependency),
        token: str = Depends(token_dependency),
    ) -> UserInfo:
        headers = {"Authorization": f"Bearer {token}"}
        endpoint = "/auth/ap1/v1/user-info"
        resp = await client.get(endpoint, headers=headers)
        obj = resp.json()
        return UserInfo.parse_obj(obj)


user_dependency = UserDependency()
