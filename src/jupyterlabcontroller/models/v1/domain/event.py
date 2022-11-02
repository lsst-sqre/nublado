"""Event model for jupyterlab-controller."""

from typing import Dict, TypeAlias

from ..external.event import EventQueue

EventMap: TypeAlias = Dict[str, EventQueue]
