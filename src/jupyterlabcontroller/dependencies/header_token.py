from fastapi import HTTPException, Request


class TokenDependency:
    async def __call__(self, request: Request) -> str:
        token = request.headers.get("X-Auth-Request-Token")
        if token is None:
            raise HTTPException(status_code=422, detail="Unprocessable Entity")
        return token


token_dependency = TokenDependency()
