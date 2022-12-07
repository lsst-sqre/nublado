"""Event model for jupyterlab-controller."""

from collections import deque
from typing import Deque, Dict

from ..v1.event import Event


class EventMap:
    def __init__(self) -> None:
        self._dict: Dict[str, Deque[Event]] = dict()

    def get(self, key: str) -> Deque[Event]:
        return self._dict.get(key, deque())

    def set(self, key: str, item: Deque[Event]) -> None:
        self._dict[key] = item

    def remove(self, key: str) -> None:
        del self._dict[key]
