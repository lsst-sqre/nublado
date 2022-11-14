"""Models for jupyterlab-controller."""

from typing import Dict, TypeAlias

from ..v1.lab import UserData

UserMap: TypeAlias = Dict[str, UserData]
