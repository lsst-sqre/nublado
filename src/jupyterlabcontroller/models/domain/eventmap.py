"""Event model for jupyterlab-controller."""

from collections import deque
from typing import Deque, Dict

from ..v1.event import Event


class EventMap:
    def __init__(self) -> None:
        self._dict: Dict[str, Deque[Event]] = dict()

    def get(self, key: str) -> Deque[Event]:
        if key not in self._dict:
            self._dict[key] = deque()
        return self._dict[key]

    def set(self, key: str, item: Deque[Event]) -> None:
        self._dict[key] = item

    def remove(self, key: str) -> None:
        try:
            del self._dict[key]
        except KeyError:
            pass
