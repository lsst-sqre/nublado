"""The Rubin RSP RestSpawner class.

It is designed to talk to the RSP JupyterLab Controller via a simple REST
interface described in sqr-066.
"""

from typing import Any, Dict, Optional

from httpx import AsyncClient
from jupyterhub.spawner import Spawner


class RSPRestSpawner(Spawner):
    def __init__(self) -> None:
        super().__init__()
        self.client = AsyncClient()
        self.pod_name = ""

    def get_state(self) -> Dict[str, Any]:
        state = super().get_state()
        # Do something with state
        state["pod_name"] = self.pod_name
        return state

    def load_state(self, state: Dict[str, Any]) -> None:
        # Set our own traits from state
        pass

    async def start(self) -> str:
        """Returns URL of running pod."""
        return ""

    async def stop(self) -> None:
        pass

    async def poll(self) -> Optional[int]:
        """
        Check if the pod is running.

        If it is, return None.  If it has exited, return the return code
        if we know it, or 1 if it exited but we don't know how.
        """
        pass
