"""Event model for jupyterlab-controller."""

from typing import Dict

from ..v1.lab import UserInfo
from .genericmap import GenericMap


class UserMap(GenericMap):
    def __init__(self) -> None:
        super().__init__()
        self._dict: Dict[str, UserInfo] = dict()
