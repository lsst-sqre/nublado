"""Models for the fileserver state."""

import contextlib

__all__ = ["FileserverUserMap"]


class FileserverUserMap:
    """File server state.

    All methods are async because eventually this is going to use
    Redis. Locking will be managed external to the user map.
    """

    def __init__(self) -> None:
        self._dict: dict[str, bool] = {}

    async def get(self, key: str) -> bool:
        return self._dict.get(key, False)

    async def list(self) -> list[str]:
        return list(self._dict.keys())

    async def set(self, key: str) -> None:
        self._dict[key] = True

    async def remove(self, key: str) -> None:
        with contextlib.suppress(KeyError):
            del self._dict[key]
