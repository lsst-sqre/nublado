"""Models for the fileserver state.  Note that the reason its methods are
async is that this will eventually be replaced by an implementation in
Redis."""


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

    async def bulk_update(self, new: dict[str, bool]) -> None:
        self._dict = new
