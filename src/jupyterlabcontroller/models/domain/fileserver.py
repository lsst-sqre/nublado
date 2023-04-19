"""Models for the fileserver controller"""


class FileserverUserMap:
    def __init__(self) -> None:
        self._dict: dict[str, bool] = {}

    def get(self, key: str) -> bool:
        return self._dict.get(key, False)

    def list_users(self) -> list[str]:
        return list(self._dict.keys())

    def set(self, key: str) -> None:
        self._dict[key] = True

    def remove(self, key: str) -> None:
        try:
            del self._dict[key]
        except KeyError:
            pass

    def bulk_update(self, new: dict[str, bool]) -> None:
        self._dict = new
