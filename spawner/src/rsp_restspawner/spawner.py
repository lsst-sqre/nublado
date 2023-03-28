"""Spawner class that uses a REST API to a separate Kubernetes service."""

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from typing import Any, Optional

from httpx import AsyncClient
from httpx_sse import ServerSentEvent, aconnect_sse
from jupyterhub.spawner import Spawner

from .constants import DEFAULT_ADMIN_TOKEN_FILE, LabStatus
from .errors import InvalidAuthStateError, MissingFieldError, SpawnerError
from .util import get_controller_route, get_external_instance_url

__all__ = ["RSPRestSpawner"]

_CLIENT: Optional[AsyncClient] = None
"""Cached global HTTP client so that we can share a connection pool."""


class RSPRestSpawner(Spawner):
    """Spawner class that sends requests to the RSP lab controller.

    Rather than having JupyterHub spawn labs directly and therefore need
    Kubernetes permissions to manage every resource that a user's lab
    environment may need, the Rubin Science Platform manages all labs in a
    separate privileged lab controller process. JupyterHub makes RESTful HTTP
    requests to that service using either its own credentials or the
    credentials of the user.

    See `SQR-066 <https://sqr-066.lsst.io/>`__ for the full design.

    Notes
    -----
    This class uses a single process-global shared `httpx.AsyncClient` to make
    all of its HTTP requests, rather than using one per instantiation of the
    spawner class. Each user gets their own spawner, so this approach allows
    all requests to share a connection pool.

    This client is created on first use and never shut down. To be strictly
    correct, it should be closed properly when the JupyterHub process is
    exiting, but we haven't yet figured out how to hook into the appropriate
    part of the JupyterHub lifecycle to do that.
    """

    def __init__(self, *args: Optional[Any], **kwargs: Optional[Any]) -> None:
        super().__init__(*args, **kwargs)
        self.ctrl_url = os.getenv(
            "JUPYTERLAB_CONTROLLER_URL",
            (
                get_external_instance_url()
                + get_controller_route()
                + "/spawner/v1"
            ),
        )

    @property
    def _client(self) -> AsyncClient:
        """Shared `httpx.AsyncClient`."""
        global _CLIENT
        if not _CLIENT:
            _CLIENT = AsyncClient()
        return _CLIENT

    async def start(self) -> str:
        """Returns expected URL of running pod
        (returns before creation completes)."""
        r = await self._client.post(
            f"{self.ctrl_url}/labs/{self.user.name}/create",
            headers=await self._user_authorization(),
            json={
                "options": self.options_from_form(self.user_options),
                "env": self.get_env(),
            },
            timeout=600.0,
            follow_redirects=False,
        )
        if r.status_code == 409 or r.status_code == 303:
            # For the Conflict we need to check the status ourself.
            # This route requires an admin token
            r = await self._client.get(
                f"{self.ctrl_url}/labs/{self.user.name}",
                headers=self._admin_authorization(),
            )
        if r.status_code == 200:
            obj = r.json()
            if "internal_url" in obj:
                return obj["internal_url"]
            raise MissingFieldError(f"Response '{obj}' missing 'internal_url'")
        raise SpawnerError(r)

    async def stop(self) -> None:
        r = await self._client.delete(
            f"{self.ctrl_url}/labs/{self.user.name}",
            timeout=300.0,
            headers=self._admin_authorization(),
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
        r = await self._client.get(
            f"{self.ctrl_url}/labs/{self.user.name}",
            headers=self._admin_authorization(),
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
        r = await self._client.get(
            f"{self.ctrl_url}/lab-form/{self.user.name}",
            headers=await self._user_authorization(),
        )
        if r.status_code != 200:
            raise SpawnerError(r)
        return r.text

    async def progress(self) -> AsyncIterator[dict[str, bool | int | str]]:
        progress = 0
        timeout = timedelta(seconds=150)
        try:
            async for sse in self._get_progress_events(timeout):
                if sse.event == "complete":
                    yield {
                        "progress": 90,
                        "message": sse.data or "Lab pod running",
                        "ready": True,
                    }
                    return
                elif sse.event == "progress":
                    try:
                        progress = int(sse.data)
                    except ValueError:
                        msg = "Invalid progress value: {sse.data}"
                        self.log.error(msg)
                    continue
                elif sse.event in ("info", "error", "failed"):
                    if not sse.data:
                        continue
                    yield {
                        "progress": progress,
                        "message": sse.data,
                        "ready": False,
                    }
                    if sse.event == "failed":
                        return
                else:
                    self.log.error(f"Unknown event type {sse.event}")
        except asyncio.TimeoutError:
            msg = f"No update from event stream in {timeout}s, giving up"
            self.log.error(msg)

    async def _get_progress_events(
        self, timeout: timedelta
    ) -> AsyncIterator[ServerSentEvent]:
        """Get server-sent events for the user's pod-spawning status.

        Parameters
        ----------
        timeout
            Timeout for the request.

        Yields
        ------
        ServerSentEvent
            Next event from the lab controller's event stream.
        """
        url = f"{self.ctrl_url}/labs/{self.user.name}/events"
        kwargs = {
            "timeout": timeout.total_seconds(),
            "headers": await self._user_authorization(),
        }
        async with aconnect_sse(self._client, "GET", url, **kwargs) as source:
            async for sse in source.aiter_sse():
                yield sse

    def _admin_authorization(self) -> dict[str, str]:
        """Create authorization headers for auth as JupyterHub itself.

        Returns
        -------
        dict of str to str
            Suitable headers for authenticating to the lab controller as the
            JupyterHub pod.
        """
        path = Path(
            os.getenv("RESTSPAWNER_ADMIN_TOKEN_FILE", DEFAULT_ADMIN_TOKEN_FILE)
        )
        token = path.read_text().strip()
        return {"Authorization": f"Bearer {token}"}

    async def _user_authorization(self) -> dict[str, str]:
        """Create authorization headers for auth as the user.

        Returns
        -------
        dict of str to str
            Suitable headers for authenticating to the lab controller as the
            user.

        Raises
        ------
        InvalidAuthStateError
            Raised if there is no ``token`` attribute in the user's
            authentication state. This should always be provided by
            `~rsp_restspawner.auth.GafaelfawrAuthenticator`.
        """
        auth_state = await self.user.get_auth_state()
        if "token" not in auth_state:
            raise InvalidAuthStateError("No token in user auth state")
        return {"Authorization": "Bearer " + auth_state["token"]}
