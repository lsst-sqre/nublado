from typing import Dict, List

from ..models.v1.domain.event import Event

__all__ = ["user_events"]

user_events: Dict[str, List[Event]] = {}
