from fastapi import Depends, HTTPException, Request

from ..constants import ADMIN_SCOPE, USER_SCOPE
from ..models.context import Context
from .context import context_dependency
from .header_token import token_dependency


class UserTokenDependency:
    async def __call__(
        self,
        request: Request,
        token: str = Depends(token_dependency),
        context: Context = Depends(context_dependency),
    ) -> str:
        if token != context.token:
            raise HTTPException(status_code=424, detail="Failed Dependency")
        if USER_SCOPE not in context.token_scopes:
            raise HTTPException(status_code=403, detail="Forbidden")
        return context.token


user_token_dependency = UserTokenDependency()


class AdminTokenDependency:
    async def __call__(
        self,
        request: Request,
        token: str = Depends(token_dependency),
        context: Context = Depends(context_dependency),
    ) -> str:
        if token != context.token:
            raise HTTPException(status_code=424, detail="Failed Dependency")
        if ADMIN_SCOPE not in context.token_scopes:
            raise HTTPException(status_code=403, detail="Forbidden")
        return context.token


admin_token_dependency = AdminTokenDependency()
