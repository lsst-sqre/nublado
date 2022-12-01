from fastapi import HTTPException, Request


class TokenDependency:
    async def __call__(self, request: Request) -> str:
        auth_hdr = request.headers.get("Authorization")
        if auth_hdr is None:
            raise HTTPException(status_code=422, detail="Unprocessable Entity")
        if auth_hdr[:7].lower() != "bearer ":
            raise HTTPException(status_code=422, detail="Unprocessable Entity")
        token = auth_hdr[7:]
        return token


token_dependency = TokenDependency()
