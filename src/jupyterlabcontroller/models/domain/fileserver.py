"""Models for the fileserver state.  Async because eventually this is going
to use Redis.  Locking will be managed external to the user map."""


class FileserverUserMap:
    def __init__(self) -> None:
        self._dict: dict[str, bool] = {}

    async def get(self, key: str) -> bool:
        return self._dict.get(key, False)

    async def list_users(self) -> list[str]:
        return list(self._dict.keys())

    async def set(self, key: str) -> None:
        self._dict[key] = True

    async def remove(self, key: str) -> None:
        try:
            del self._dict[key]
        except KeyError:
            pass
