"""Event model for jupyterlab-controller."""

from typing import Deque, Dict, Optional

from ..v1.event import Event


class EventMap:
    def __init__(self) -> None:
        self._dict: Dict[str, Deque[Event]] = dict()

    def get(self, key: str) -> Optional[Deque[Event]]:
        return self._dict.get(key)

    def set(self, key: str, item: Deque[Event]) -> None:
        self._dict[key] = item

    def remove(self, key: str) -> None:
        del self._dict[key]
