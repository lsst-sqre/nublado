from fastapi import Depends
from httpx import AsyncClient
from safir.dependencies.http_client import http_client_dependency

from ..models.v1.external.userdata import UserInfo


async def get_user_from_token(
    token: str,
    client: AsyncClient = Depends(http_client_dependency),
) -> UserInfo:
    endpoint = "/auth/ap1/v1/user-info"
    headers = {"Authorization": f"Bearer {token}"}
    resp = await client.get(endpoint, headers=headers)
    obj = resp.json()
    return UserInfo.parse_obj(obj)
