from typing import Optional

from httpx import AsyncClient

_client: Optional[AsyncClient] = None


async def get_client(token: str = "") -> AsyncClient:
    """This is the way to retrieve an AsyncClient to make HTTP requests.
    The httpx.AsyncClient is roughly equivalent to a requests Session.

    This object needs to be created inside an async function, so by
    calling this, you ensure it exists, or create it if it doesn't.

    Since there are some connection pools, we don't want to be creating
    these all the time.  Better to just reuse one.

    This is taken from Nublado v2, except using httpx, not aiohttp."""
    global _client
    if _client is None:
        _client = AsyncClient()
    return _client
