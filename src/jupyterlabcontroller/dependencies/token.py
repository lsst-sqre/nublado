from fastapi import Depends, Header, HTTPException, Request

from ..constants import ADMIN_SCOPE, USER_SCOPE
from ..models.context import Context
from ..util import extract_bearer_token
from .context import context_dependency


class UserTokenDependency:
    async def __call__(
        self,
        request: Request,
        authorization: str = Header(...),
        context: Context = Depends(context_dependency),
    ) -> str:
        token = extract_bearer_token(authorization)
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
        authorization: str = Header(...),
        context: Context = Depends(context_dependency),
    ) -> str:
        token = extract_bearer_token(authorization)
        if token != context.token:
            raise HTTPException(status_code=424, detail="Failed Dependency")
        if ADMIN_SCOPE not in context.token_scopes:
            raise HTTPException(status_code=403, detail="Forbidden")
        return context.token


admin_token_dependency = AdminTokenDependency()
