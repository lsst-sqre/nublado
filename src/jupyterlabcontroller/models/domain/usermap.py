"""Event model for jupyterlab-controller."""

from ..v1.lab import LabStatus, PodState, UserData


class UserMap:
    def __init__(self) -> None:
        self._dict: dict[str, UserData] = {}

    def get(self, key: str) -> UserData | None:
        return self._dict.get(key)

    def list_users(self) -> list[str]:
        return list(self._dict.keys())

    def set(self, key: str, item: UserData) -> None:
        self._dict[key] = item

    def set_pod_state(self, key: str, pod_state: PodState) -> None:
        self._dict[key].pod = pod_state

    def set_status(self, key: str, status: LabStatus) -> None:
        self._dict[key].status = status

    def set_internal_url(self, key: str, url: str) -> None:
        self._dict[key].internal_url = url

    def clear_internal_url(self, key: str) -> None:
        self._dict[key].internal_url = None

    def remove(self, key: str) -> None:
        del self._dict[key]

    async def running(self) -> list[str]:
        return [
            self._dict[k].username
            for k in self._dict.keys()
            if self._dict[k].status == LabStatus.RUNNING
        ]
