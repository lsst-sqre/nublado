"""Event model for jupyterlab-controller."""

from typing import Any, Dict, List


class GenericMap:
    def __init__(self) -> None:
        self._dict: Dict[str, Any] = dict()

    # https://stackoverflow.com/questions/4014621

    def __setitem__(self, key: str, item: Any) -> None:
        self._dict[key] = item

    def __getitem__(self, key: str) -> Any:
        return self._dict[key]

    def __repr__(self) -> str:
        return repr(self._dict)

    def __len__(self) -> int:
        return len(self._dict)

    def __delitem__(self, key: str) -> None:
        del self._dict[key]

    def clear(self) -> None:
        self._dict.clear()

    def copy(self) -> Dict[str, Any]:
        return self._dict.copy()

    def has_key(self, k: str) -> bool:
        return k in self._dict

    def update(self, *args: Any, **kwargs: Any) -> None:
        self._dict.update(*args, **kwargs)

    @property
    def list(self) -> List[Any]:
        return list(self._dict.values())

    def get(self, key: str) -> Any:
        return self._dict.get(key)

    def set(self, key: str, item: Any) -> None:
        self._dict[key] = item

    def remove(self, key: str) -> None:
        del self._dict[key]
