"""Event model for jupyterlab-controller."""

from typing import Dict

from ..v1.event import EventQueue
from .genericmap import GenericMap


class EventMap(GenericMap):
    def __init__(self) -> None:
        super().__init__()
        self._dict: Dict[str, EventQueue] = dict()
