"""The Rubin RSP RestSpawner class.

It is designed to talk to the RSP JupyterLab Controller via a simple REST
interface described in sqr-066.
"""

import os
from typing import Any, Dict, List, Optional

from httpx import AsyncClient, Headers
from jupyterhub.spawner import Spawner

from .admin import get_admin_token
from .constants import LabStatus
from .http import get_client
from .util import get_namespace


class RSPRestSpawner(Spawner):
    def __init__(self) -> None:
        super().__init__()
        self.pod_name = ""
        self.admin_token = get_admin_token()
        self.base_url = os.getenv(
            "EXTERNAL_INSTANCE_URL", "http://localhost:8080"
        )
        namespace = get_namespace()
        self.ctrl_url = os.getenv(
            "JUPYTERLAB_CONTROLLER_URL",
            f"{self.base_url}/{namespace}/spawner/v1",
        )

    def get_state(self) -> Dict[str, Any]:
        # Do something with state
        state = super().get_state()
        state["pod_name"] = self.pod_name
        return state

    def load_state(self, state: Dict[str, Any]) -> None:
        # Set our own traits from state
        self.user_token = state["token"]

    async def start(self) -> str:
        """Returns expected URL of running pod
        (returns before creation completes)."""
        formdata = self.options_from_form(self.user_options)
        lab_specification = {
            "options": formdata,
            "env": {
                "EXTERNAL_INSTANCE_URL": self.base_url,
                "JUPYTERHUB_API_TOKEN": self.api_token,
                "JUPYTERHUB_API_URL": self.hub.api_url,
                "ACCESS_TOKEN": self.user_token,
            },
        }
        client = await self._configure_client()
        r = await client.post(
            f"{self.ctrl_url}/{self.user}/create",
            data=lab_specification,
        )
        if r.status_code == 409:
            # Do something?  hook them up to their running pod?  Not sure.
            pass
        return r.text  # I think

    async def stop(self) -> None:
        client = await self._configure_client(token=self.admin_token)
        await client.delete(f"{self.ctrl_url}/{self.user}")

    async def poll(self) -> Optional[int]:
        """
        Check if the pod is running.

        If it is, return None.  If it has exited, return the return code
        if we know it, or 1 if it exited but we don't know how.

        Because we do not have direct access to the pod's exit code, we
        are here going to return 1 for "The pod does not exist from the
        perspective of the lab controller" and 2 for "We tried to start
        a pod, but it failed."
        """
        client = await self._configure_client()
        r = await client.get(f"{self.ctrl_url}/user-status")
        if r.status_code == 404:
            return 1  # No lab for user.
        result = r.json()
        if result.status in (
            LabStatus.STARTING,
            LabStatus.RUNNING,
            LabStatus.TERMINATING,
        ):
            return None
        return 2  # Pod failed; we could check 'pod' and 'events' to see why.

    async def _options_form_default(self) -> str:
        client = await self._configure_client(content_type="text/html")
        r = await client.get(
            f"{self.base_url}/spawner/v1/lab-form/{self.user}",
        )
        return r.text

    async def _configure_client(
        self,
        token: str = "",
        content_type: str = "application/json",
    ) -> AsyncClient:
        """This returns the (global) AsyncClient, configured with the
        correct authorization (default: the user token) and content
        type (default: 'application/json').
        """
        if token == "":
            token = self.user_token
        client = await get_client()
        client.headers = Headers(
            {
                "Authorization": f"Bearer {token}",
                "Content-Type": content_type,
            }
        )
        return client

    def options_from_form(
        self, formdata: Dict[str, List[str]]
    ) -> Dict[str, List[str]]:
        """All the processing is done in the Lab Controller; this is just a
        passthrough."""
        return formdata
