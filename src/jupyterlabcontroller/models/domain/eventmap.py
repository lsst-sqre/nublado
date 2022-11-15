"""Event model for jupyterlab-controller."""

from typing import Dict, Optional

from ..v1.event import EventQueue


class EventMap:
    def __init__(self) -> None:
        self._dict: Dict[str, EventQueue] = dict()

    def get(self, key: str) -> Optional[EventQueue]:
        return self._dict.get(key)

    def set(self, key: str, item: EventQueue) -> None:
        self._dict[key] = item

    def remove(self, key: str) -> None:
        del self._dict[key]
