"""The Rubin RSP RestSpawner class.

It is designed to talk to the RSP JupyterLab Controller via a simple REST
interface described in sqr-066.
"""

import asyncio

from typing import Any, Dict, Future, Optional

from jupyterhub.spawner import Spawner

from httpx import AsyncClient

class RubinRSPRestSpawner(Spawner):

    def __init__(self) -> None:
        super().__init__()
        self.client = AsyncClient()
        self.pod_name = ""
    
    def get_state(self) -> Dict[str, Any]:
        state = super().get_state()
        # Do something with state
        state['pod_name'] = self.pod_name
        return state

    def load_state(self, state) -> None:
        # Set our own traits from state
        pass

    async def start(self) -> str:
        """Returns URL of running pod.
        """
    
    async def stop(self) -> None:
        pass
    
    async def poll(self) ->Optional[int]:
        """
        Check if the pod is running.

        If it is, return None.  If it has exited, return the return code
        if we know it, or 1 if it exited but we don't know how.
        """
        pass

    
