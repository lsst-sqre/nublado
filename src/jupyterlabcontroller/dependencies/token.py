from fastapi import Depends, Header, HTTPException, Request

from ..constants import ADMIN_SCOPE, USER_SCOPE
from ..models.context import Context
from .context import context_dependency


class UserTokenDependency:
    async def __call__(
        self,
        request: Request,
        context: Context = Depends(context_dependency),
    ) -> str:
        if USER_SCOPE not in await context.get_token_scopes():
            raise HTTPException(status_code=403, detail="Forbidden")
        return context.token


user_token_dependency = UserTokenDependency()


class AdminTokenDependency:
    async def __call__(
        self,
        request: Request,
        authorization: str = Header(...),
        context: Context = Depends(context_dependency),
    ) -> str:
        if ADMIN_SCOPE not in await context.get_token_scopes():
            raise HTTPException(status_code=403, detail="Forbidden")
        return context.token


admin_token_dependency = AdminTokenDependency()
