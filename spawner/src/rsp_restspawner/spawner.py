"""The Rubin RSP RestSpawner class.

It is designed to talk to the RSP JupyterLab Controller via a simple REST
interface described in sqr-066.
"""

import asyncio
import os
from collections.abc import AsyncGenerator
from typing import Any, Dict, List, Optional

from httpx import AsyncClient, Headers
from jupyterhub.spawner import Spawner

from .admin import get_admin_token
from .constants import LabStatus
from .errors import SpawnerError
from .http import get_client
from .util import get_external_instance_url, get_hub_base_url, get_namespace


class RSPRestSpawner(Spawner):
    def __init__(self, *args: Optional[Any], **kwargs: Optional[Any]) -> None:
        super().__init__(*args, **kwargs)
        self.pod_name = ""
        self.admin_token = get_admin_token()
        self.external_url = get_external_instance_url()
        self.hub_base_url = get_hub_base_url()
        namespace = get_namespace()
        self.ctrl_url = os.getenv(
            "JUPYTERLAB_CONTROLLER_URL",
            f"{self.external_url}/{namespace}/spawner/v1",
        )

    async def _get_user_environment(self) -> Dict[str, str]:
        uname = self.user.name
        jhub_oauth_scopes = (
            f'["access:servers!server={uname}/", '
            f'"access:servers!user={uname}"]'
        )
        # We are only going to set the JupyterHub items here.
        # Everything else will be handled via the controller.
        return {
            "JUPYTERHUB_ACTIVITY_URL": (
                f"http://hub.{get_namespace()}:8081{self.hub_base_url}"
                f"/hub/api/users/{uname}/activity"
            ),
            "JUPYTERHUB_API_TOKEN": self.api_token,
            "JUPYTERHUB_API_URL": self.hub.api_url,
            "JUPYTERHUB_CLIENT_ID": f"jupyterhub-user-{uname}",
            "JUPYTERHUB_OAUTH_ACCESS_SCOPES": jhub_oauth_scopes,
            "JUPYTERHUB_OAUTH_CALLBACK_URL": (
                f"{self.hub_base_url}/user/{uname}/oauth_callback"
            ),
            "JUPYTERHUB_OAUTH_SCOPES": jhub_oauth_scopes,
            "JUPYTERHUB_SERVICE_PREFIX": f"{self.hub_base_url}/user/{uname}/",
            "JUPYTERHUB_SERVICE_URL": (
                f"http://0.0.0.0:8888{self.hub_base_url}/user/{uname}/"
            ),
            "JUPYTERHUB_USER": uname,
        }

    async def start(self) -> str:
        """Returns expected URL of running pod
        (returns before creation completes)."""
        formdata = self.options_from_form(self.user_options)
        uname = self.user.name
        lab_specification = {
            "options": formdata,
            "env": await self._get_user_environment(),
        }
        client = await self._configure_client()
        r = await client.post(
            f"{self.ctrl_url}/labs/{uname}/create",
            json=lab_specification,
            timeout=600.0,
            follow_redirects=False,
        )
        if r.status_code == 409 or r.status_code == 303:
            #
            # The 409 is Conflict; so just return the Lab URL, same as
            # we would for a new Lab.
            #
            # We don't actually do anything with the redirect; it returns
            # the URL to ask the controller (as admin) for lab status.
            #
            # One of the objects we create (for exactly this reason) is a K8s
            # service.  K8s will know how to route to it, so we just return
            # its (in-cluster) DNS name as the hostname, which gets resolved
            # to an IP address by the K8s resolver.
            user_ns = f"{get_namespace()}-{uname}"
            return f"http://lab.{user_ns}:8888"
        raise SpawnerError(r)

    async def stop(self) -> None:
        client = await self._configure_client(token=self.admin_token)
        r = await client.delete(
            f"{self.ctrl_url}/labs/{self.user.name}", timeout=300.0
        )
        if r.status_code == 202 or r.status_code == 404:
            # We're deleting it, or it wasn't there to start with.
            return
        raise SpawnerError(r)

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
        if r.status_code != 200:
            raise SpawnerError(r)
        result = r.json()
        if result["status"] in (
            LabStatus.STARTING,
            LabStatus.RUNNING,
            LabStatus.TERMINATING,
        ):
            return None
        return 2  # Pod failed; we could check 'pod' and 'events' to see why.

    async def options_form(self, spawner: Spawner) -> str:
        if spawner != self:
            raise RuntimeError(
                f"options_form(): self->{self}, spawner->{spawner}"
            )
        client = await self._configure_client(content_type="text/html")
        form_url = f"{self.ctrl_url}/lab-form/{self.user.name}"
        r = await client.get(form_url)
        if r.status_code != 200:
            raise SpawnerError(r)
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
            auth_state = await self.user.get_auth_state()
            token = auth_state.get("token", "UNINITIALIZED")
        auth = f"Bearer {token}"
        client = await get_client()
        client.headers = Headers(
            {
                "Authorization": auth,
                "Content-Type": content_type,
            }
        )
        return client

    def options_from_form(
        self, formdata: Dict[str, List[str]]
    ) -> Dict[str, List[str]]:
        """Do all the parsing on the controller side.  This is just a
        passthrough."""
        return formdata

    async def progress(self) -> AsyncGenerator:
        progress: Optional[int] = None
        prev_progress: Optional[int] = None
        message: Optional[str] = None
        event_endpoint = f"{self.ctrl_url}/labs/{self.user.name}/events"
        client = await self._configure_client(content_type="text/event-stream")
        timeout = 150.0
        try:
            self.logger.debug(
                f"About to check event stream {client} for progress"
            )
            async with client.stream(
                "GET", event_endpoint, timeout=timeout
            ) as resp:
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    self.logger.debug(f"Received line: {line}")
                    if line.startswith("event: "):
                        e_type = line[7:]
                        continue
                    if e_type == "complete":
                        pm = {
                            "progress": 90,
                            "message": "Lab pod running",
                            "ready": True,
                        }
                        yield pm
                        return
                    if line.startswith("data: "):
                        if e_type == "progress":
                            progress = int(line[6:])
                        if e_type in ("info", "error", "failed"):
                            message = line[6:]
                            progress = progress or prev_progress or 50
                    if message and progress:
                        pm = {
                            "progress": progress,
                            "message": message,
                            "ready": False,
                        }
                        message = None
                        prev_progress = progress
                        progress = None
                        yield pm
                        if e_type in ("error", "failed"):
                            raise RuntimeError(pm["message"])
        except asyncio.TimeoutError:
            self.logger.error(
                f"No update from event stream in {timeout}s; giving up."
            )
            return
