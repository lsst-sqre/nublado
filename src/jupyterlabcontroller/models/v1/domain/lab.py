"""Models for jupyterlab-controller."""

from typing import Dict, TypeAlias

from ..external.lab import UserData

UserMap: TypeAlias = Dict[str, UserData]
