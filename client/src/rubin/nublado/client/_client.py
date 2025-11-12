"""Client for the Nublado JupyterHub and JupyterLab service.

Allows the caller to login to spawn labs and execute code within the lab.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import aclosing
from datetime import UTC, datetime, timedelta

import structlog
from httpx import HTTPError, Timeout
from httpx_sse import EventSource
from pydantic import ValidationError
from rubin.repertoire import DiscoveryClient
from structlog.stdlib import BoundLogger

from ._exceptions import (
    NubladoProtocolError,
    NubladoSpawnError,
    NubladoWebError,
)
from ._http import JupyterAsyncClient
from ._models import (
    NotebookExecutionResult,
    NubladoImage,
    SpawnProgressMessage,
)
from ._session import JupyterLabSessionManager

__all__ = ["NubladoClient"]


class JupyterSpawnProgress:
    """Async iterator returning spawn progress messages.

    This parses messages from the progress API, which is an EventStream API
    that provides status messages for a spawning lab.

    Parameters
    ----------
    event_source
        Open EventStream connection.
    logger
        Logger to use.
    """

    def __init__(self, event_source: EventSource, logger: BoundLogger) -> None:
        self._source = event_source
        self._logger = logger
        self._start = datetime.now(tz=UTC)

    async def __aiter__(self) -> AsyncGenerator[SpawnProgressMessage]:
        """Iterate over spawn progress events.

        Yields
        ------
        SpawnProgressMessage
            The next progress message.

        Raises
        ------
        httpx.HTTPError
            Raised if a protocol error occurred while connecting to the
            EventStream API or reading or parsing a message from it.
        """
        async with aclosing(self._source.aiter_sse()) as sse_events:
            async for sse in sse_events:
                try:
                    event_dict = sse.json()
                    event = SpawnProgressMessage(
                        progress=event_dict["progress"],
                        message=event_dict["message"],
                        ready=event_dict.get("ready", False),
                    )
                except Exception as e:
                    err = f"{type(e).__name__}: {e!s}"
                    msg = f"Error parsing progress event, ignoring: {err}"
                    self._logger.warning(msg, type=sse.event, data=sse.data)
                    continue

                # Log the event and yield it.
                now = datetime.now(tz=UTC)
                elapsed = int((now - self._start).total_seconds())
                status = "complete" if event.ready else "in progress"
                msg = f"Spawn {status} ({elapsed}s elapsed): {event.message}"
                self._logger.info(msg, elapsed=elapsed, status=status)
                yield event


class NubladoClient:
    """Client for talking to JupyterHub and Jupyter labs that use Nublado.

    Parameters
    ----------
    username
        User whose lab should be managed.
    token
        Token to use for authentication.
    discovery_client
        If given, Repertoire_ discovery client to use. Otherwise, a new client
        will be created.
    logger
        Logger to use. If not given, the default structlog logger will be
        used.
    timeout
        Timeout to use when talking to JupyterHub and Jupyter lab. This is
        used as a connection, read, and write timeout for all regular HTTP
        calls.
    """

    def __init__(
        self,
        username: str,
        token: str,
        *,
        discovery_client: DiscoveryClient | None = None,
        logger: BoundLogger | None = None,
        timeout: timedelta = timedelta(seconds=30),
    ) -> None:
        self._username = username
        self._discovery = discovery_client or DiscoveryClient()
        self._logger = logger or structlog.get_logger()
        self._timeout = timeout
        self._token = token
        self._client = self._build_jupyter_client()

    async def aclose(self) -> None:
        """Close the underlying HTTP connection pool.

        This invalidates the client object. It can no longer be used after
        this method is called.
        """
        await self._client.aclose()

    async def auth_to_hub(self) -> None:
        """Retrieve the JupyterHub home page.

        This resets the underlying HTTP client to clear cookies and force a
        complete refresh of stored state, including XSRF tokens. Less
        aggressive reset mechanisms resulted in periodic errors about stale
        XSRF cookies.

        Raises
        ------
        NubladoDiscoveryError
            Raised if Nublado is missing from service discovery.
        NubladoRedirectError
            Raised if the URL is outside of Nublado's URL space or there is a
            redirect loop.
        NubladoWebError
            Raised if an HTTP error occurred talking to JupyterHub.
        rubin.repertoire.RepertoireError
            Raised if there was an error talking to service discovery.
        """
        await self._client.aclose()
        self._client = self._build_jupyter_client()
        await self._client.get("hub/home", fetch_mode="navigate")

    async def auth_to_lab(self) -> None:
        """Authenticate to the user's JupyterLab.

        Request the top-level lab page, which will force the OpenID Connect
        authentication with JupyterHub and set authentication cookies. This
        will be done implicitly the first time, but for long-running clients,
        you may need to do this periodically to refresh credentials.

        Raises
        ------
        NubladoDiscoveryError
            Raised if Nublado is missing from service discovery.
        NubladoRedirectError
            Raised if the URL is outside of Nublado's URL space or there is a
            redirect loop.
        NubladoWebError
            Raised if an HTTP error occurred talking to JupyterHub or
            JupyterLab.
        rubin.repertoire.RepertoireError
            Raised if there was an error talking to service discovery.
        """
        route = f"user/{self._username}/lab"
        await self._client.get(route, fetch_mode="navigate")

    async def is_lab_stopped(self, *, log_running: bool = False) -> bool:
        """Determine if the lab is fully stopped.

        Parameters
        ----------
        log_running
            Log a warning with additional information if the lab still
            exists.

        Raises
        ------
        NubladoDiscoveryError
            Raised if Nublado is missing from service discovery.
        NubladoRedirectError
            Raised if the URL is outside of Nublado's URL space or there is a
            redirect loop.
        NubladoWebError
            Raised if an HTTP error occurred talking to JupyterHub.
        rubin.repertoire.RepertoireError
            Raised if there was an error talking to service discovery.
        """
        route = f"hub/api/users/{self._username}"
        r = await self._client.get(route, add_referer=True)

        # We currently only support a single lab per user, so the lab is
        # running if and only if the server data for the user is not empty.
        data = r.json()
        result = data["servers"] == {}
        if log_running and not result:
            msg = "User API data still shows running lab"
            self._logger.warning(msg, servers=data["servers"])
        return result

    def lab_session(
        self,
        notebook_name: str | None = None,
        *,
        kernel_name: str = "lsst",
        max_websocket_size: int | None = None,
        websocket_open_timeout: timedelta = timedelta(seconds=60),
    ) -> JupyterLabSessionManager:
        """Create a lab session manager.

        Returns a context manager object so must be called via ``async with``
        or the equivalent. The lab session will automatically be deleted when
        the context manager exits.

        Parameters
        ----------
        notebook_name
            Name of the notebook we will be running, which is passed to the
            session and might influence logging on the lab side. If set, the
            session type will be set to ``notebook``. If not set, the session
            type will be set to ``console``.
        kernel_name
            Name of the kernel to use for the session.
        max_websocket_size
            Maximum size of a WebSocket message, or `None` for no limit.
        websocket_open_timeout
            Timeout for opening a WebSocket.

        Returns
        -------
        JupyterLabSessionManager
            Context manager to open the WebSocket session.
        """
        return JupyterLabSessionManager(
            username=self._username,
            jupyter_client=self._client,
            kernel_name=kernel_name,
            notebook_name=notebook_name,
            max_websocket_size=max_websocket_size,
            websocket_open_timeout=websocket_open_timeout,
            logger=self._logger,
        )

    async def run_notebook(
        self,
        content: str,
        *,
        kernel_name: str | None = None,
        read_timeout: timedelta | None = None,
    ) -> NotebookExecutionResult:
        """Run a notebook via the Nublado notebook execution extension.

        This runs the notebook using :command:`nbconvert` via a Nublado
        JupyterLab extension, rather than executing it cell-by-cell within a
        session and kernel.

        Parameters
        ----------
        content
            Content of the notebook to execute.
        kernel_name
            If provided, override the default kernel name.
        read_timeout
            If provided, overrides the default read timeout for Nublado API
            calls. The default timeout is 30 seconds and the notebook
            execution is synchronous, so providing a longer timeout is
            recommended unless the notebook is quick to execute. This will
            only change the read timeout, used when waiting for results, not
            the timeouts on connecting and sending the request.

        Returns
        -------
        NotebookExecutionResult
            Execution results from the notebook. If the notebook execution
            failed due to an issue with a cell, rather than a lower-level
            issue with notebook execution, the ``error`` attribute of this
            result will be filled in.

        Raises
        ------
        NubladoDiscoveryError
            Raised if Nublado is missing from service discovery.
        NubladoProtocolError
            Raised if the return value from the notebook execution extension
            could not be parsed.
        NubladoRedirectError
            Raised if the URL is outside of Nublado's URL space or there is a
            redirect loop.
        NubladoWebError
            Raised if an HTTP error occurred talking to JupyterHub or
            JupyterLab.
        rubin.repertoire.RepertoireError
            Raised if there was an error talking to service discovery.
        """
        timeout = None
        if read_timeout:
            timeout = Timeout(
                self._timeout.total_seconds(),
                read=read_timeout.total_seconds(),
            )
        headers = None
        if kernel_name:
            headers = {"X-Kernel-Name": kernel_name}
        route = f"user/{self._username}/rubin/execution"
        r = await self._client.post(
            route, content=content, timeout=timeout, extra_headers=headers
        )
        result = r.json()
        self._logger.debug("Got notebook execution result", result=result)
        try:
            return NotebookExecutionResult.model_validate(result)
        except ValidationError as e:
            msg = f"Cannot parse notebook execution results: {e!s}"
            raise NubladoProtocolError(msg) from e

    async def spawn_lab(self, config: NubladoImage) -> None:
        """Spawn a Jupyter lab pod.

        Parameters
        ----------
        config
            Image configuration.

        Raises
        ------
        NubladoDiscoveryError
            Raised if Nublado is missing from service discovery.
        NubladoRedirectError
            Raised if the URL is outside of Nublado's URL space or there is a
            redirect loop.
        NubladoWebError
            Raised if an HTTP error occurred talking to JupyterHub.
        rubin.repertoire.RepertoireError
            Raised if there was an error talking to service discovery.
        """
        data = config.to_spawn_form()

        # Retrieving the spawn page before POSTing to it appears to trigger
        # some necessary internal state construction (and also more accurately
        # simulates a user interaction). See DM-23864.
        await self._client.get("hub/spawn", fetch_mode="navigate")

        # POST the options form to the spawn page. This should redirect to
        # the spawn-pending page, which will return a 200.
        self._logger.info(
            "Spawning lab", user=self._username, **config.to_logging_context()
        )
        await self._client.post("hub/spawn", data=data)

    async def stop_lab(self) -> None:
        """Stop the user's Jupyter lab.

        Raises
        ------
        NubladoDiscoveryError
            Raised if Nublado is missing from service discovery.
        NubladoRedirectError
            Raised if the URL is outside of Nublado's URL space or there is a
            redirect loop.
        NubladoWebError
            Raised if an HTTP error occurred talking to JupyterHub.
        rubin.repertoire.RepertoireError
            Raised if there was an error talking to service discovery.
        """
        if await self.is_lab_stopped():
            self._logger.info("Lab is already stopped")
            return
        route = f"hub/api/users/{self._username}/server"
        self._logger.info("Stopping lab", user=self._username)
        await self._client.delete(route, add_referer=True)

    async def wait_for_spawn(self) -> None:
        """Wait for lab spawn to complete without monitoring it.

        This method can be used instead of `watch_spawn_progress` if the
        caller is not interested in the spawn progress messages. It will
        return when the spawn is complete.

        Raises
        ------
        NubladoDiscoveryError
            Raised if Nublado is missing from service discovery.
        NubladoRedirectError
            Raised if the URL is outside of Nublado's URL space or there is a
            redirect loop.
        NubladoSpawnError
            Raised if the spawn failed.
        NubladoWebError
            Raised if an HTTP error occurred talking to JupyterHub.
        rubin.repertoire.RepertoireError
            Raised if there was an error talking to service discovery.
        """
        start = datetime.now(tz=UTC)
        message = None
        log = []
        async with aclosing(self.watch_spawn_progress()) as progress:
            async for message in progress:
                log.append(message.message)
                if message.ready:
                    self._logger.info("Lab spawn complete")
                    return

        # If this fell through, that means the progress iterator closed
        # without sending a ready message, which means the spawn failed. Use
        # the last message as the error message.
        error = message.message if message else "No output from spawn attempt"
        raise NubladoSpawnError(error, log, self._username, started_at=start)

    async def watch_spawn_progress(
        self,
    ) -> AsyncGenerator[SpawnProgressMessage]:
        """Monitor lab spawn progress.

        This is an EventStream API, which provides a stream of events until
        the lab is spawned or the spawn fails. The caller can distinguish
        between the two by checking if the ``ready`` field of the last yielded
        message is `True`, indicating the spawn succeeded.

        Yields
        ------
        SpawnProgressMessage
            Next progress message from JupyterHub.

        Raises
        ------
        NubladoDiscoveryError
            Raised if Nublado is missing from service discovery.
        NubladoRedirectError
            Raised if the URL is outside of Nublado's URL space or there is a
            redirect loop.
        NubladoWebError
            Raised if an HTTP error occurred talking to JupyterHub.
        rubin.repertoire.RepertoireError
            Raised if there was an error talking to service discovery.
        """
        start = datetime.now(tz=UTC)
        route = f"hub/api/users/{self._username}/server/progress"
        stream_manager = await self._client.open_sse_stream(route)
        try:
            async with stream_manager as stream:
                progress = aiter(JupyterSpawnProgress(stream, self._logger))
                async with aclosing(progress):
                    async for message in progress:
                        yield message
        except HTTPError as e:
            exc = NubladoWebError.from_exception(e, self._username)
            exc.started_at = start
            raise exc from e

    def _build_jupyter_client(self) -> JupyterAsyncClient:
        """Construct a new HTTP client to talk to Jupyter."""
        return JupyterAsyncClient(
            discovery_client=self._discovery,
            logger=self._logger,
            timeout=self._timeout,
            token=self._token,
            username=self._username,
        )
