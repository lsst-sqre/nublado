"""Event model for jupyterlab-controller."""

from typing import Dict, TypeAlias

from ..v1.event import EventQueue

EventMap: TypeAlias = Dict[str, EventQueue]
