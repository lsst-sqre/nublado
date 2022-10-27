from fastapi import Depends

from ..models.v1.external.userdata import UserInfo
from ..services.namespace import get_user_namespace
from .token import user_dependency


class NamespaceDependency:
    async def __call__(self, user: UserInfo = Depends(user_dependency)) -> str:
        username = user.username
        return get_user_namespace(username)


namespace_dependency = NamespaceDependency()
