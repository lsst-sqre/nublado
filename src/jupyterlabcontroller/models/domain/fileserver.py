"""Models for the fileserver controller"""
from dataclasses import dataclass

from ...exceptions import DuplicateUserError, InvalidUserError
from ..v1.lab import LabStatus as FileserverPodStatus
from ..v1.lab import PodState, UserInfo


@dataclass
class FileserverData:
    pod_state: PodState
    """State of fileserver pod"""

    pod_status: FileserverPodStatus
    """Fileserver pod status"""

    user: UserInfo
    """Fileserver user information"""


class FileserverUserMap:
    def __init__(self) -> None:
        self._dict: dict[str, FileserverData] = {}

    def get(self, key: str) -> FileserverData | None:
        return self._dict.get(key)

    def list_users(self) -> list[str]:
        return list(self._dict.keys())

    def set(self, key: str, item: FileserverData) -> None:
        if key != item.user.username:
            raise InvalidUserError()
        self._dict[key] = item

    def set_pod_state(self, key: str, pod_state: PodState) -> None:
        self._dict[key].pod_state = pod_state

    def set_status(self, key: str, status: FileserverPodStatus) -> None:
        self._dict[key].status = status

    def set_user(self, key: str, userinfo: UserInfo) -> None:
        if key != userinfo.username:
            raise InvalidUserError()
        self._dict[key].user = userinfo

    def add_user(self, user: UserInfo) -> None:
        current_users = list(self._dict.keys())
        username = user.username
        if username in current_users:
            raise DuplicateUserError()
        self.set(
            username,
            FileserverData(
                pod_state=PodState.PENDING,
                pod_status=FileserverPodStatus.MISSING,
                user=user,
            ),
        )

    def remove(self, key: str) -> None:
        del self._dict[key]

    async def running(self) -> list[str]:
        return [
            k
            for k in self._dict.keys()
            if self._dict[k].status == FileserverPodStatus.RUNNING
        ]
