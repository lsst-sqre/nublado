"""The Rubin RSP RestSpawner class.

It is designed to talk to the RSP JupyterLab Controller via a simple REST
interface described in sqr-066.
"""

import asyncio
import os
from collections.abc import AsyncGenerator
from typing import Any, Optional

from httpx import Headers
from jupyterhub.spawner import Spawner

from .constants import LabStatus
from .errors import MissingFieldError, SpawnerError
from .event import Event
from .http import get_client
from .util import (
    get_admin_token,
    get_controller_route,
    get_external_instance_url,
)


class RSPRestSpawner(Spawner):
    def __init__(self, *args: Optional[Any], **kwargs: Optional[Any]) -> None:
        super().__init__(*args, **kwargs)
        self.pod_name = ""
        self.admin_token = get_admin_token()
        self.ctrl_url = os.getenv(
            "JUPYTERLAB_CONTROLLER_URL",
            (
                get_external_instance_url()
                + get_controller_route()
                + "/spawner/v1"
            ),
        )

    async def start(self) -> str:
        """Returns expected URL of running pod
        (returns before creation completes)."""
        formdata = self.options_from_form(self.user_options)
        uname = self.user.name
        lab_specification = {
            "options": formdata,
            "env": self.get_env(),  # From superclass
        }
        client = await get_client()
        r = await client.post(
            f"{self.ctrl_url}/labs/{uname}/create",
            headers=await self._configure_client_headers(),
            json=lab_specification,
            timeout=600.0,
            follow_redirects=False,
        )
        if r.status_code == 409 or r.status_code == 303:
            # For the Conflict we need to check the status ourself.
            # This route requires an admin token
            r = await client.get(
                f"{self.ctrl_url}/labs/{uname}",
                headers=await self._configure_client_headers(
                    token=self.admin_token
                ),
            )
        if r.status_code == 200:
            obj = r.json()
            if "internal_url" in obj:
                return obj["internal_url"]
            raise MissingFieldError(f"Response '{obj}' missing 'internal_url'")
        raise SpawnerError(r)

    async def stop(self) -> None:
        client = await get_client()
        r = await client.delete(
            f"{self.ctrl_url}/labs/{self.user.name}",
            timeout=300.0,
            headers=await self._configure_client_headers(
                token=self.admin_token
            ),
        )
        if r.status_code == 202 or r.status_code == 404:
            # We're deleting it, or it wasn't there to start with.
            return
        raise SpawnerError(r)

    async def poll(self) -> Optional[int]:
        """
        Check if the pod is running.

        If it is, return None.  If it has exited, return the return code
        if we know it, or 0 if it exited but we don't know how.

        Because we do not have direct access to the pod's exit code, we
        are here going to return 0 for "The pod does not exist from the
        perspective of the lab controller" (which assumes a good or unknown
        exit status) and 1 for "We tried to start a pod, but it failed," which
        implies a failure (i.e. non-zero) exit status.
        """
        client = await get_client()
        r = await client.get(
            f"{self.ctrl_url}/labs/{self.user.name}",
            headers=await self._configure_client_headers(),
        )
        if r.status_code == 404:
            return 0  # No lab for user.
        if r.status_code != 200:
            raise SpawnerError(r)
        result = r.json()
        if result["status"] in (
            LabStatus.STARTING,
            LabStatus.RUNNING,
            LabStatus.TERMINATING,
        ):
            return None
        return 1  # Pod failed; we could check 'pod' and 'events' to see why.

    async def options_form(self, spawner: Spawner) -> str:
        client = await get_client()
        form_url = f"{self.ctrl_url}/lab-form/{self.user.name}"
        r = await client.get(
            form_url,
            headers=await self._configure_client_headers(
                content_type="text/html"
            ),
        )
        if r.status_code != 200:
            raise SpawnerError(r)
        return r.text

    async def progress(self) -> AsyncGenerator:
        progress: Optional[int] = None
        prev_progress: Optional[int] = None
        message: Optional[str] = None
        event_endpoint = f"{self.ctrl_url}/labs/{self.user.name}/events"
        client = await get_client()
        timeout = 150.0
        try:
            async with client.stream(
                "GET",
                event_endpoint,
                timeout=timeout,
                headers=await self._configure_client_headers(
                    content_type="text/event-stream"
                ),
            ) as resp:
                lines: list[str] = list()
                async for line in resp.aiter_lines():
                    line = line.strip()
                    ev: Optional[Event] = None
                    if not line:
                        if not lines:
                            # No event to dispatch
                            continue
                        # An empty line means "Dispatch the event"
                        ev = Event.from_lines(lines)
                        lines = []
                    else:
                        lines.append(line)
                        continue
                    if ev.event_type == "complete":
                        yield {
                            "progress": 90,
                            "message": "Lab pod running",
                            "ready": True,
                        }
                        return
                    progress = ev.progress()
                    message = ev.message()
                    if message:
                        progress = progress or prev_progress or 50
                        pm = {
                            "progress": progress,
                            "message": message,
                            "ready": False,
                        }
                        message = None
                        prev_progress = progress
                        progress = None
                        yield pm
                        if ev.event_type in ("error", "failed"):
                            raise RuntimeError(pm["message"])
        except asyncio.TimeoutError:
            self.log.error(
                f"No update from event stream in {timeout}s; giving up."
            )
            return

    async def _configure_client_headers(
        self,
        token: str = "",
        content_type: str = "application/json",
    ) -> Headers:
        """This returns headers configured with the correct
        authorization (default: the user token) and content type
        (default: 'application/json').
        """
        if token == "":
            auth_state = await self.user.get_auth_state()
            token = auth_state.get("token", "UNINITIALIZED")
        auth = f"Bearer {token}"
        headers = Headers(
            {
                "Authorization": auth,
                "Content-Type": content_type,
            }
        )
        return headers
