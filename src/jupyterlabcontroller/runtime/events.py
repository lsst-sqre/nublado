from typing import Dict, List

from ..models.event import Event

__all__ = ["user_events"]

user_events: Dict[str, List[Event]] = {}
