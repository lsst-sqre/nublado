"""Spawner class that uses a REST API to a separate Kubernetes service."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Coroutine
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from functools import wraps
from pathlib import Path
from typing import Any, Optional, ParamSpec, TypeVar

from httpx import AsyncClient, HTTPError
from httpx_sse import ServerSentEvent, aconnect_sse
from jupyterhub.spawner import Spawner
from traitlets import Unicode, default

from .exceptions import (
    ControllerWebError,
    InvalidAuthStateError,
    MissingFieldError,
    SpawnFailedError,
)

P = ParamSpec("P")
T = TypeVar("T")

__all__ = [
    "LabStatus",
    "RSPRestSpawner",
]

_CLIENT: Optional[AsyncClient] = None
"""Cached global HTTP client so that we can share a connection pool."""


class LabStatus(str, Enum):
    """Possible status conditions of a user's pod per the lab controller.

    Keep this in sync with the status values reported by the status endpoint
    of the lab controller.
    """

    STARTING = "starting"
    RUNNING = "running"
    TERMINATING = "terminating"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class SpawnEvent:
    """JupyterHub spawning event."""

    progress: int
    """Percentage of progress, from 0 to 100."""

    message: str
    """Event description."""

    severity: str
    """Log message severity."""

    complete: bool = False
    """Whether the event indicated spawning is done."""

    failed: bool = False
    """Whether the event indicated spawning failed."""

    @classmethod
    def from_sse(cls, sse: ServerSentEvent, progress: int) -> SpawnEvent:
        """Convert from a server-sent event from the lab controller.

        Parameters
        ----------
        sse
            Event from the lab controller.
        progress
            Current progress percentage, if the event doesn't specify one.
        """
        try:
            data = sse.json()
            if not (set(data.keys()) <= {"message", "progress"}):
                raise ValueError("Invalid key in SSE data")
            if "progress" in data:
                progress = int(data["progress"])
                if progress < 0 or progress > 100:
                    raise ValueError(f"Invalid progress value {progress}")
        except Exception:
            data = {"message": sse.data}
        data["progress"] = progress

        if sse.event == "complete":
            data["progress"] = 75
            return cls(**data, severity="info", complete=True)
        elif sse.event in ("info", "error"):
            return cls(**data, severity=sse.event)
        elif sse.event == "failed":
            return cls(**data, severity="error", failed=True)
        else:
            return cls(**data, severity="unknown")

    def to_dict(self) -> dict[str, int | str]:
        """Convert to the dictionary expected by JupyterHub."""
        return {
            "progress": self.progress,
            "message": f"[{self.severity}] {self.message}",
        }


def _convert_exception(
    f: Callable[P, Coroutine[None, None, T]]
) -> Callable[P, Coroutine[None, None, T]]:
    """Convert ``httpx`` exceptions to `ControllerWebError`."""

    @wraps(f)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        try:
            return await f(*args, **kwargs)
        except HTTPError as e:
            raise ControllerWebError.from_exception(e) from e

    return wrapper


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

    admin_token_path = Unicode(
        "/etc/gafaelfawr/token",
        help="""
        Path to the Gafaelfawr token for JupyterHub itself.

        This token will be used to authenticate to the lab controller routes
        that JupyterHub is allowed to call directly such as to get lab status
        and delete a lab.
        """,
    ).tag(config=True)

    controller_url = Unicode(
        "http://localhost:8080/nublado",
        help="""
        Base URL for the Nublado lab controller.

        All URLs for talking to the Nublado lab controller will be constructed
        relative to this base URL.
        """,
    ).tag(config=True)

    # Do not preserve any of JupyterHub's environment variables in the default
    # environment for labs.
    @default("env_keep")
    def _env_keep_default(self) -> list[str]:
        return []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        # Holds the events from a spawn in progress.
        self._events: list[SpawnEvent] = []

        # Triggers used to notify listeners of new events. Each listener gets
        # its own trigger.
        self._triggers: list[asyncio.Event] = []

        # Holds the future representing a spawn in progress, used by the
        # progress method to know when th spawn is finished and it should
        # exit.
        self._start_future: Optional[asyncio.Task[str]] = None

    @property
    def _client(self) -> AsyncClient:
        """Shared `httpx.AsyncClient`."""
        global _CLIENT
        if not _CLIENT:
            _CLIENT = AsyncClient()
        return _CLIENT

    async def get_url(self) -> str:
        """Determine the URL of a running lab.

        Returns
        -------
        str
            URL of the lab if we can retrieve it from the lab controller,
            otherwise the saved URL in the spawner object.

        Notes
        -----
        JupyterHub recommends implementing this if the spawner has some
        independent way to retrieve the lab URL, since it allows JupyterHub to
        recover if it was killed in the middle of spawning a lab and that
        spawn finished successfully while JupyterHub was down. This method is
        only called if `poll` returns `None`.

        JupyterHub does not appear to do any error handling of failures of
        this method, so it should not raise an exception, just fall back on
        the stored URL and let the probe fail if that lab does not exist.
        """
        try:
            return await self._get_internal_url()
        except Exception:
            msg = f"Unable to get URL of running lab for {self.user.name}"
            self.log.exception(msg)
            return await super().get_url()

    @_convert_exception
    async def options_form(self, spawner: Spawner) -> str:
        """Retrieve the options form for this user from the lab controller.

        Parameters
        ----------
        spawner
            Another copy of the spawner (not used). It's not clear why
            JupyterHub passes this into this method.

        Raises
        ------
        ControllerWebError
            Raised on failure to talk to the lab controller or a failure
            response from the lab controller.
        InvalidAuthStateError
            Raised if there is no ``token`` attribute in the user's
            authentication state. This should always be provided by
            `~rsp_restspawner.auth.GafaelfawrAuthenticator`.
        """
        r = await self._client.get(
            self._controller_url("lab-form", self.user.name),
            headers=await self._user_authorization(),
        )
        r.raise_for_status()
        return r.text

    @_convert_exception
    async def poll(self) -> Optional[int]:
        """Check if the pod is running.

        Returns
        -------
        int or None
            If the pod is starting, running, or terminating, return `None`.
            If the pod does not exist, return 0. If the pod exists in a failed
            state, return 1.

        Raises
        ------
        ControllerWebError
            Raised on failure to talk to the lab controller or a failure
            response from the lab controller.

        Notes
        -----
        In theory, this is supposed to be the exit status of the Jupyter lab
        process. This isn't something we know in the classic sense since the
        lab is a Kubernetes pod. We only know that something failed if the
        record of the lab is hanging around in a failed state, so use a simple
        non-zero exit status for that. Otherwise, we have no way to
        distinguish between a pod that was shut down without error and a pod
        that was stopped, so use an exit status of 0 in both cases.
        """
        r = await self._client.get(
            self._controller_url("labs", self.user.name),
            headers=self._admin_authorization(),
        )
        if r.status_code == 404:
            return 0
        else:
            r.raise_for_status()
        result = r.json()
        return 1 if result["status"] == LabStatus.FAILED else None

    async def progress(self) -> AsyncIterator[dict[str, int | str]]:
        """Monitor the progress of a spawn.

        This method is the internal implementation of the progress API. It
        provides an iterator of spawn events and then ends when the spawn
        succeeds or fails.

        Yields
        ------
        dict of str to str or int
            Dictionary representing the event with fields ``progress``,
            containing an integer completion percentage, and ``message``,
            containing a human-readable description of the event.

        Notes
        -----
        This method must never raise exceptions, since those will be treated
        as unhandled exceptions by JupyterHub. If anything fails, just stop
        the iterator. It doesn't do any HTTP calls itself, just monitors the
        events created by `start`.

        Uses the internal ``_start_future`` attribute to track when the
        related `start` method has completed.
        """
        next_event = 0
        complete = False

        # Insert a trigger into the trigger list that will be notified by the
        # in-progress spawn.
        trigger = asyncio.Event()
        self._triggers.append(trigger)

        # Capture the current future and event stream in a local variable so
        # that we consistently monitor the same invocation of start. If that
        # one aborts and someone kicks off another one, we want to keep
        # following the first one until it completes, not switch streams to
        # the second one.
        start_future = self._start_future
        events = self._events

        # We were apparently called before start was called, so there's
        # nothing to report.
        if not start_future:
            return

        while not complete:
            trigger.clear()
            if start_future.done():
                # Indicate that we're done, but continue to execute the rest
                # of the loop. We want to process any events received before
                # the spawner finishes and report them before ending the
                # stream.
                complete = True

            # This logic tries to ensure that we don't repeat events even
            # though start will be adding more events while we're working.
            len_events = len(events)
            for i in range(next_event, len_events):
                yield events[i].to_dict()
            next_event = len_events

            # Wait until we're notified that there are new events or we time
            # out on the spawn. This is not the correct timeout (start_timeout
            # is a bound on the total time, not each event). It's just an
            # arbitrary timeout to ensure we don't wait forever, which is
            # guaranteed to be longer than a spawn can take.
            if not complete:
                try:
                    await asyncio.wait_for(trigger.wait(), self.start_timeout)
                except TimeoutError:
                    complete = True

    def start(self) -> asyncio.Task[str]:
        """Start the user's pod.

        Initiates the pod start operation and then waits for the pod to spawn
        by watching the event stream, converting those events into the format
        expected by JupyterHub and returned by `progress`. Returns only when
        the pod is running and JupyterHub should start waiting for the lab
        process to start responding.

        Returns
        -------
        asyncio.Task
            Running task monitoring the progress of the spawn. This task will
            be started before it is returned. When the task is complete, it
            will return the cluster-internal URL of the running Jupyter lab
            process.

        Notes
        -----
        The actual work is done in `_start`. This is a tiny wrapper to do
        bookkeeping on the event stream and record the running task so that
        `progress` can notice when the task is complete and return.

        It is tempting to only initiate the pod spawn here, return
        immediately, and then let JupyterHub follow progress via the
        `progress` API. However, this is not what JupyterHub is expecting.
        The entire spawn process must happen before the `start` method returns
        for the configured timeouts to work properly; once `start` has
        returned, JupyterHub only allows a much shorter timeout for the lab to
        fully start.

        In addition, JupyterHub handles exceptions from `start` and correctly
        recognizes that the pod has failed to start, but exceptions from
        `progress` are treated as uncaught exceptions and cause the UI to
        break. Therefore, `progress` must never fail and all operations that
        may fail need to be done in `start`.
        """
        self._start_future = asyncio.create_task(self._start())
        return self._start_future

    @_convert_exception
    async def _start(self) -> str:
        """Spawn the user's lab.

        This is the core of the work of `start`. Ask the lab controller to
        create the lab and monitor its progress, generating events that are
        stored in the ``_events`` attribute for `progress`.

        JupyterHub will automatically call stop on failed spawns, so we don't
        need to do that ourselves.

        Returns
        -------
        str
            Cluster-internal URL of the running Jupyter lab process.

        Raises
        ------
        ControllerWebError
            Raised on failure to talk to the lab controller or a failure
            response from the lab controller.
        InvalidAuthStateError
            Raised if there is no ``token`` attribute in the user's
            authentication state. This should always be provided by
            `~rsp_restspawner.auth.GafaelfawrAuthenticator`.
        MissingFieldError
            Raised if the response from the lab controller is invalid.
        SpawnFailedError
            Raised if the lab controller said that the spawn failed.

        Notes
        -----
        JupyterHub itself arranges for two spawns for the same spawner object
        to not be running at the same time, so we ignore that possibility.
        """
        progress = 0

        # Clear the event list (by replacing the previous list so that any
        # running progress calls see the old list, not the new one), and
        # notify any existing triggers and then clear the trigger list.
        self._events = []
        for trigger in self._triggers:
            trigger.set()
        self._triggers = []

        # Ask the Nublado lab controller to do the spawn and monitor its
        # progress until complete.
        try:
            r = await self._client.post(
                self._controller_url("labs", self.user.name, "create"),
                headers=await self._user_authorization(),
                json={
                    "options": self.options_from_form(self.user_options),
                    "env": self.get_env(),
                },
                timeout=self.start_timeout,
            )

            # 409 (Conflict) indicates the user already has a running pod. See
            # if it really is running, and if so, return its URL.
            if r.status_code == 409:
                event = SpawnEvent(
                    progress=75, message="Lab already running", severity="info"
                )
                self._events.append(event)
                return await self._get_internal_url()
            else:
                r.raise_for_status()

            # The spawn is now in progress. Monitor the events endpoint until
            # we get a completion or failure event.
            timeout = timedelta(seconds=self.start_timeout)
            async for sse in self._get_progress_events(timeout):
                if sse.event == "ping":
                    # Sent by sse-starlette to keep the connection alive.
                    continue
                event = SpawnEvent.from_sse(sse, progress)
                if event.progress:
                    progress = event.progress
                self._events.append(event)
                if event.complete:
                    break
                if event.failed:
                    raise SpawnFailedError(event.message)

            # Return the internal URL of the spawned pod.
            return await self._get_internal_url()

        finally:
            # Ensure that we set all the triggers just before we exit so that
            # none of the progress calls will get stranded waiting for a lock.
            for trigger in self._triggers:
                trigger.set()

    @_convert_exception
    async def stop(self) -> None:
        """Delete any running pod for the user.

        If the pod does not exist, treat that as success.

        Raises
        ------
        ControllerWebError
            Raised on failure to talk to the lab controller or a failure
            response from the lab controller.
        """
        r = await self._client.delete(
            self._controller_url("labs", self.user.name),
            timeout=300.0,
            headers=self._admin_authorization(),
        )
        if r.status_code == 404:
            # Nothing to delete, treat that as success.
            return
        else:
            r.raise_for_status()

    def _controller_url(self, *components: str) -> str:
        """Build a URL to the Nublado lab controller.

        Parameters
        ----------
        *components
            Path component of the URL.

        Returns
        -------
        str
            URL to the lab controller using the configured base URL.
        """
        return self.controller_url + "/spawner/v1/" + "/".join(components)

    async def _get_internal_url(self) -> str:
        """Get the cluster-internal URL of a user's pod.

        Raises
        ------
        httpx.HTTPError
            Raised on failure to talk to the lab controller or a failure
            response from the lab controller.
        MissingFieldError
            Raised if the response from the lab controller is invalid.
        """
        r = await self._client.get(
            self._controller_url("labs", self.user.name),
            headers=self._admin_authorization(),
        )
        r.raise_for_status()
        url = r.json().get("internal_url")
        if not url:
            msg = f"Invalid lab status for {self.user.name}"
            raise MissingFieldError(msg)
        return url

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

        Raises
        ------
        httpx.HTTPError
            Raised on failure to talk to the lab controller or a failure
            response from the lab controller.
        InvalidAuthStateError
            Raised if there is no ``token`` attribute in the user's
            authentication state. This should always be provided by
            `~rsp_restspawner.auth.GafaelfawrAuthenticator`.
        """
        url = self._controller_url("labs", self.user.name, "events")
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
        path = Path(self.admin_token_path)
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
