"""Event model for jupyterlab-controller."""

from typing import Dict, List, Optional

from ..v1.lab import LabStatus, UserData


class UserMap:
    def __init__(self) -> None:
        self._dict: Dict[str, UserData] = dict()

    def get(self, key: str) -> Optional[UserData]:
        return self._dict.get(key)

    def set(self, key: str, item: UserData) -> None:
        self._dict[key] = item

    def set_status(self, key: str, status: LabStatus) -> None:
        self._dict[key].status = status

    def remove(self, key: str) -> None:
        del self._dict[key]

    async def running(self) -> List[str]:
        return [
            self._dict[k].username
            for k in self._dict.keys()
            if self._dict[k].status == LabStatus.RUNNING
        ]
