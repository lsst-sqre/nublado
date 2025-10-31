"""Client for the Nublado JupyterHub and JupyterLab service.

Allows the caller to login to spawn labs and execute code within the lab.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Coroutine
from contextlib import AbstractAsyncContextManager, aclosing
from datetime import UTC, datetime, timedelta
from functools import wraps
from pathlib import Path
from types import TracebackType
from typing import Concatenate, Literal, Self
from uuid import uuid4

import httpx
import structlog
from httpx import HTTPError
from httpx_sse import EventSource
from rubin.repertoire import DiscoveryClient
from structlog.stdlib import BoundLogger
from websockets.asyncio.client import ClientConnection
from websockets.exceptions import WebSocketException

from ._exceptions import (
    CodeExecutionError,
    ExecutionAPIError,
    JupyterTimeoutError,
    JupyterWebError,
    JupyterWebSocketError,
    NubladoClientSlackException,
)
from ._http import JupyterAsyncClient
from ._models import (
    CodeContext,
    JupyterOutput,
    NotebookExecutionResult,
    NubladoImage,
    SpawnProgressMessage,
)
from ._util import source_list_by_cell

__all__ = ["JupyterLabSession", "NubladoClient"]


class _aclosing_iter[T: AsyncIterator](AbstractAsyncContextManager):  # noqa: N801
    """Automatically close async iterators that are generators.

    Python supports two ways of writing an async iterator: a true async
    iterator, and an async generator. Generators support additional async
    context, such as yielding from inside an async context manager, and
    therefore require cleanup by calling their `aclose` method once the
    generator is no longer needed. This step is done automatically by the
    async loop implementation when the generator is garbage-collected, but
    this may happen at an arbitrary point and produces pytest warnings
    saying that the `aclose` method on the generator was never called.

    This class provides a variant of `contextlib.aclosing` that can be
    used to close generators masquerading as iterators. Many Python libraries
    implement `__aiter__` by returning a generator rather than an iterator,
    which is equivalent except for this cleanup behavior. Async iterators do
    not require this explicit cleanup step because they don't support async
    context managers inside the iteration. Since the library is free to change
    from a generator to an iterator at any time, and async iterators don't
    require this cleanup and don't have `aclose` methods, the `aclose` method
    should be called only if it exists.
    """

    def __init__(self, thing: T) -> None:
        self.thing = thing

    async def __aenter__(self) -> T:
        return self.thing

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        # Only call aclose if the method is defined, which we take to mean that
        # this iterator is actually a generator.
        if getattr(self.thing, "aclose", None):
            await self.thing.aclose()  # type: ignore[attr-defined]
        return False


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
        async with _aclosing_iter(self._source.aiter_sse()) as sse_events:
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


class JupyterLabSession:
    """Represents an open session with a Jupyter Lab.

    A context manager providing an open WebSocket session. The session will be
    automatically deleted when exiting the context manager. Objects of this
    type should be created by calling `NubladoClient.open_lab_session`.

    Parameters
    ----------
    username
        User the session is for.
    base_url
        Base URL for talking to JupyterLab.
    kernel_name
        Name of the kernel to use for the session.
    notebook_name
        Name of the notebook we will be running, which is passed to the
        session and might influence logging on the lab side. If set, the
        session type will be set to ``notebook``. If not set, the session type
        will be set to ``console``.
    http_client
        HTTP client to talk to the Jupyter lab.
    logger
        Logger to use.
    """

    _IGNORED_MESSAGE_TYPES = (
        "comm_close",
        "comm_msg",
        "comm_open",
        "display_data",
        "execute_input",
        "execute_result",
        "status",
    )
    """WebSocket messge types ignored by the parser.

    Jupyter labs send a lot of types of WebSocket messages to provide status
    or display formatted results. For our purposes, we only care about output
    and errors, but we want to warn about unrecognized messages so that we
    notice places where we may be missing part of the protocol. These are
    message types that we know we don't care about and should ignore.
    """

    def __init__(
        self,
        *,
        username: str,
        jupyter_client: JupyterAsyncClient,
        kernel_name: str = "LSST",
        notebook_name: str | None = None,
        max_websocket_size: int | None,
        websocket_open_timeout: timedelta = timedelta(seconds=60),
        logger: BoundLogger,
    ) -> None:
        self._username = username
        self._client = jupyter_client
        self._kernel_name = kernel_name
        self._notebook_name = notebook_name
        self._max_websocket_size = max_websocket_size
        self._websocket_open_timeout = websocket_open_timeout
        self._logger = logger

        self._session_id: str | None = None
        self._session: AbstractAsyncContextManager[ClientConnection] | None
        self._session = None
        self._socket: ClientConnection | None = None

    async def __aenter__(self) -> Self:
        """Create the session and open the WebSocket connection.

        Raises
        ------
        JupyterTimeoutError
            Raised if the attempt to open a WebSocket to the lab timed out.
        JupyterWebError
            Raised if an error occurred while creating the lab session.
        JupyterWebSocketError
            Raised if a protocol or network error occurred while trying to
            create the WebSocket.
        """
        # This class implements an explicit context manager instead of using
        # an async generator and contextlib.asynccontextmanager, and similarly
        # explicitly calls the __aenter__ and __aexit__ methods in the
        # WebSocket library rather than using it as a context manager.
        #
        # Initially, it was implemented as a generator, but when using that
        # approach the code after the yield in the generator was called at an
        # arbitrary time in the future, rather than when the context manager
        # exited. This meant that it was often called after the httpx client
        # had been closed, which meant it was unable to delete the lab session
        # and raised background exceptions. This approach allows more explicit
        # control of when the context manager is shut down and ensures it
        # happens immediately when the context exits.
        route = f"user/{self._username}/api/sessions"
        notebook = self._notebook_name
        body = {
            "kernel": {"name": self._kernel_name},
            "name": notebook or "(no notebook)",
            "path": notebook if notebook else uuid4().hex,
            "type": "notebook" if notebook else "console",
        }
        start = datetime.now(tz=UTC)

        # Create the kernel.
        try:
            r = await self._client.post(route, json=body)
        except HTTPError as e:
            raise JupyterWebError.raise_from_exception_with_timestamps(
                e, self._username, {}, start
            ) from e
        response = r.json()
        self._session_id = response["id"]
        kernel = response["kernel"]["id"]

        # Open a WebSocket to the now-running kernel.
        route = f"user/{self._username}/api/kernels/{kernel}/channels"
        start = datetime.now(tz=UTC)
        self._logger.debug("Opening WebSocket connection")
        try:
            self._session = await self._client.open_websocket(
                route,
                open_timeout=self._websocket_open_timeout,
                max_size=self._max_websocket_size,
            )
            self._socket = await self._session.__aenter__()
        except WebSocketException as e:
            user = self._username
            raise JupyterWebSocketError.from_exception(
                e, user, started_at=start
            ) from e
        except TimeoutError as e:
            msg = "Timed out attempting to open WebSocket to lab session"
            user = self._username
            raise JupyterTimeoutError(msg, user, started_at=start) from e
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> Literal[False]:
        """Shut down the open WebSocket and delete the session."""
        username = self._username
        session_id = self._session_id

        # Close the WebSocket.
        if self._session:
            start = datetime.now(tz=UTC)
            try:
                await self._session.__aexit__(exc_type, exc_val, exc_tb)
            except WebSocketException as e:
                raise JupyterWebSocketError.from_exception(
                    e, username, started_at=start
                ) from e
            self._session = None
            self._socket = None

        # Delete the lab session.
        route = f"user/{username}/api/sessions/{session_id}"
        try:
            await self._client.delete(route)
        except HTTPError as e:
            # Be careful to not raise an exception if we're already processing
            # an exception, since the exception from inside the context
            # manager is almost certainly more interesting than the exception
            # from closing the lab session.
            if exc_type:
                self._logger.exception("Failed to close session")
            else:
                start = datetime.now(tz=UTC)
                raise JupyterWebError.raise_from_exception_with_timestamps(
                    e, self._username, {}, start
                ) from e

        return False

    async def run_python(
        self, code: str, context: CodeContext | None = None
    ) -> str:
        """Run a block of Python code in a Jupyter lab kernel.

        Parameters
        ----------
        code
            Code to run.

        Returns
        -------
        str
            Output from the kernel.

        Raises
        ------
        CodeExecutionError
            Raised if an error was reported by the Jupyter lab kernel.
        JupyterWebSocketError
            Raised if there was a WebSocket protocol error while running code
            or waiting for the response.
        JupyterWebError
            Raised if called before entering the context and thus before
            creating the WebSocket session.
        """
        if not self._socket:
            raise JupyterWebError(
                "JupyterLabSession not opened", user=self._username
            )
        start = datetime.now(tz=UTC)
        message_id = uuid4().hex
        request = {
            "header": {
                "username": self._username,
                "version": "5.4",
                "session": self._session_id,
                "date": start.isoformat(),
                "msg_id": message_id,
                "msg_type": "execute_request",
            },
            "parent_header": {},
            "channel": "shell",
            "content": {
                "code": code,
                "silent": False,
                "store_history": False,
                "user_expressions": {},
                "allow_stdin": False,
            },
            "metadata": {},
            "buffers": {},
        }

        # Send the message and consume messages waiting for the response.
        result = ""
        try:
            await self._socket.send(json.dumps(request))
            async with _aclosing_iter(aiter(self._socket)) as messages:
                async for message in messages:
                    try:
                        output = self._parse_message(message, message_id)
                    except CodeExecutionError as e:
                        e.code = code
                        e.started_at = start
                        _annotate_exception_from_context(e, context)
                        raise
                    except Exception as e:
                        error = f"{type(e).__name__}: {e!s}"
                        msg = "Ignoring unparsable web socket message"
                        self._logger.warning(msg, error=error, message=message)
                        continue

                    # Accumulate the results if they are of interest, and exit
                    # and return the results if this message indicated the end
                    # of execution.
                    if not output:
                        continue
                    result += output.content
                    if output.done:
                        break
        except WebSocketException as e:
            user = self._username
            new_exc = JupyterWebSocketError.from_exception(e, user)
            new_exc.started_at = start
            raise new_exc from e

        # Return the accumulated output.
        return result

    async def run_notebook(
        self, notebook: Path, context: CodeContext | None = None
    ) -> list[str]:
        """Run a notebook of Python code in a Jupyter lab kernel.

        Parameters
        ----------
        notebook
            Path of notebook (relative to $HOME) to run.
        context
            Optional set of overrides for exception reporting.

        Returns
        -------
        list[str]
            Output from the kernel, one string per cell.

        Raises
        ------
        CodeExecutionError
            Raised if an error was reported by the Jupyter lab kernel.
        JupyterWebSocketError
            Raised if there was a WebSocket protocol error while running code
            or waiting for the response.
        JupyterWebError
            Raised if called before entering the context and thus before
            creating the WebSocket session.
        """
        route = f"user/{self._username}/files/{notebook!s}"
        self._logger.debug(f"Getting content from {route}")
        resp = await self._client.get(route)
        notebook_text = resp.text
        sources = source_list_by_cell(notebook_text)
        self._logger.debug(f"Content: {sources}")
        retlist: list[str] = []
        for cellsrc in sources:
            try:
                output = await self.run_python_cell(
                    cellsrc.source, context=context
                )
            except (
                CodeExecutionError,
                JupyterWebSocketError,
                JupyterWebError,
            ) as exc:
                if not context:
                    context = CodeContext()
                # Add annotations (if not provided) describing error location
                if not context.cell:
                    context.cell = cellsrc.cell_id
                if not context.cell_number:
                    context.cell_number = f"#{cellsrc.cell_number}"
                if not context.notebook:
                    context.notebook = notebook.name
                if not context.path:
                    context.path = str(notebook)
                if not context.cell_source:
                    context.cell_source = "\n".join(cellsrc.source)
                _annotate_exception_from_context(exc, context)
                raise
            retlist.append(output)
        return retlist

    async def run_python_cell(
        self, source: list[str], context: CodeContext | None = None
    ) -> str:
        """Run a cell of Python code in a Jupyter lab kernel.

        Parameters
        ----------
        source
            code to run
        context
            context of source code to run

        Returns
        -------
        str
            Output from the kernel, one string per cell.

        Raises
        ------
        CodeExecutionError
            Raised if an error was reported by the Jupyter lab kernel.
        JupyterWebSocketError
            Raised if there was a WebSocket protocol error while running code
            or waiting for the response.
        JupyterWebError
            Raised if called before entering the context and thus before
            creating the WebSocket session.
        """
        current = ""
        for idx, line in list(enumerate(source)):
            try:
                output = await self.run_python(line, context=context)
            except (
                CodeExecutionError,
                JupyterWebSocketError,
                JupyterWebError,
            ) as exc:
                if not context:
                    context = CodeContext()
                context.cell_source = "\n".join(source)
                # Line within cell is one-indexed
                context.cell_line_number = f"#{idx + 1}"
                context.cell_line_source = line
                _annotate_exception_from_context(exc, context)
                raise
            if output:
                current += output
        return current

    async def run_notebook_via_rsp_extension(
        self, *, path: Path | None = None, content: str | None = None
    ) -> NotebookExecutionResult:
        """Run a notebook through the RSP ``noninteractive`` extension, which
        will return the the executed notebook.

        This is our way around having to deal individually with the
        ``execute_result`` and ``data_display`` message types, which can
        represent a wild variety of use cases: those things will be found
        in the output notebook and it is the caller's responsibility to deal
        with them.

        Parameters
        ----------
        path
            Path of notebook (relative to $HOME) to run.
        content
            Notebook content as a string.  Only used if ``path`` is ``None``.

        Returns
        -------
        NotebookExecutionResult
            The executed Jupyter Notebook.

        Raises
        ------
        ExecutionAPIError
            Raised if there is an error interacting with the JupyterLab
            Notebook execution extension.

        JupyterWebError
            Raised if neither notebook path nor notebook contents are supplied.
        """
        if path is not None:
            route = f"user/{self._username}/files/{path!s}"
            self._logger.debug(f"Getting content from {route}")
            resp = await self._client.get(route)
            content = resp.text
        if not content:
            raise JupyterWebError(
                "No notebook content to execute", user=self._username
            )

        # The timeout is designed to catch issues connecting to JupyterLab but
        # to wait as long as possible for the notebook itself to execute.
        route = f"user/{self._username}/rubin/execution"
        start = datetime.now(tz=UTC)
        timeout = httpx.Timeout(5.0, read=None)
        try:
            r = await self._client.post(
                route, content=content, timeout=timeout
            )
        except httpx.ReadTimeout as e:
            raise ExecutionAPIError(
                url=str(e.request.url),
                username=self._username,
                status=500,
                reason="/rubin/execution endpoint timeout",
                method="POST",
                body=str(e),
                started_at=start,
            ) from e
        except httpx.HTTPStatusError as e:
            # This often occurs from timeouts, so we want to convert the
            # generic HTTPError to an ExecutionAPIError
            raise ExecutionAPIError(
                url=str(e.request.url),
                username=self._username,
                status=r.status_code,
                reason="Internal Server Error",
                method="POST",
                body=str(e),
                started_at=start,
            ) from e
        if r.status_code != 200:
            raise ExecutionAPIError.from_response(self._username, r)
        self._logger.debug("Got response from /rubin/execution", text=r.text)

        return NotebookExecutionResult.model_validate_json(r.text)

    def _parse_message(
        self, message: str | bytes, message_id: str
    ) -> JupyterOutput | None:
        """Parse a WebSocket message from a Jupyter lab kernel.

        Parameters
        ----------
        message
            Raw message.
        message_id
            Message ID of the message we went, so that we can look for
            replies.

        Returns
        -------
        JupyterOutput or None
            Parsed message, or `None` if the message wasn't of interest.

        Raises
        ------
        CodeExecutionError
            Raised if code execution fails.
        KeyError
            Raised if the WebSocket message wasn't in the expected format.
        """
        if isinstance(message, bytes):
            message = message.decode()
        data = json.loads(message)
        self._logger.debug("Received kernel message", message=data)

        # Ignore headers not intended for us. The web socket is rather
        # chatty with broadcast status messages.
        if data.get("parent_header", {}).get("msg_id") != message_id:
            return None

        # Analyze the message type to figure out what to do with the response.
        msg_type = data["msg_type"]
        start = datetime.now(tz=UTC)
        if msg_type in self._IGNORED_MESSAGE_TYPES:
            return None
        elif msg_type == "stream":
            return JupyterOutput(content=data["content"]["text"])
        elif msg_type == "execute_reply":
            status = data["content"]["status"]
            if status == "ok":
                return JupyterOutput(content="", done=True)
            else:
                raise CodeExecutionError(
                    user=self._username, status=status, started_at=start
                )
        elif msg_type == "error":
            error = "".join(data["content"]["traceback"])
            raise CodeExecutionError(
                user=self._username, error=error, started_at=start
            )
        else:
            msg = "Ignoring unrecognized WebSocket message"
            self._logger.warning(msg, message_type=msg_type, message=data)
            return None


def _annotate_exception_from_context(
    e: NubladoClientSlackException, context: CodeContext | None = None
) -> None:
    if not context:
        return
    if context.image is not None:
        e.annotations["image"] = context.image
    if context.notebook is not None:
        e.annotations["notebook"] = context.notebook
    if context.path is not None:
        e.annotations["path"] = context.path
    if context.cell is not None:
        e.annotations["cell"] = context.cell
    if context.cell_number is not None:
        e.annotations["cell_number"] = context.cell_number
    if context.cell_source is not None:
        e.annotations["cell_source"] = context.cell_source
    if context.cell_line_number is not None:
        e.annotations["cell_line_number"] = context.cell_line_number
    if context.cell_line_source is not None:
        e.annotations["cell_line_source"] = context.cell_line_source


def _convert_exception[**P, T](
    f: Callable[Concatenate[NubladoClient, P], Coroutine[None, None, T]],
) -> Callable[Concatenate[NubladoClient, P], Coroutine[None, None, T]]:
    """Convert web error to `~rubin.nublado.client.JupyterWebError`."""

    @wraps(f)
    async def wrapper(
        client: NubladoClient, *args: P.args, **kwargs: P.kwargs
    ) -> T:
        start = datetime.now(tz=UTC)
        try:
            return await f(client, *args, **kwargs)
        except HTTPError as e:
            raise JupyterWebError.raise_from_exception_with_timestamps(
                e, client.username, {}, start
            ) from e

    return wrapper


def _convert_generator_exception[**P, T](
    f: Callable[Concatenate[NubladoClient, P], AsyncGenerator[T]],
) -> Callable[Concatenate[NubladoClient, P], AsyncGenerator[T]]:
    """Convert web errors to a `~rubin.nublado.client.JupyterWebError`."""

    @wraps(f)
    async def wrapper(
        client: NubladoClient, *args: P.args, **kwargs: P.kwargs
    ) -> AsyncGenerator[T]:
        start = datetime.now(tz=UTC)
        generator = f(client, *args, **kwargs)
        try:
            async with aclosing(generator):
                async for result in generator:
                    yield result
        except HTTPError as e:
            raise JupyterWebError.raise_from_exception_with_timestamps(
                e, client.username, {}, start
            ) from e

    return wrapper


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

    Attributes
    ----------
    username
        User whose lab is managed by this object.

    Notes
    -----
    This class creates its own `httpx.AsyncClient` for each instance, separate
    from the one used by the rest of the application, since it needs to
    isolate the cookies set by JupyterHub and the lab from those for any other
    user.

    Although principally intended as a Lab/Hub client, the underlying
    `httpx.AsyncClient` is exposed via the `http` property.
    """

    def __init__(
        self,
        *,
        username: str,
        token: str,
        discovery_client: DiscoveryClient | None = None,
        logger: BoundLogger | None = None,
        timeout: timedelta = timedelta(seconds=30),
    ) -> None:
        self.username = username
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

    @_convert_exception
    async def auth_to_hub(self) -> None:
        """Retrieve the JupyterHub home page.

        This resets the underlying HTTP client to clear cookies and force a
        complete refresh of stored state, including XSRF tokens. Less
        aggressive reset mechanisms resulted in periodic errors about stale
        XSRF cookies.

        Raises
        ------
        JupyterProtocolError
            Raised if no ``_xsrf`` cookie was set in the reply from the lab.
        """
        await self._client.aclose()
        self._client = self._build_jupyter_client()
        await self._client.get("hub/home", fetch_mode="navigate")

    @_convert_exception
    async def auth_to_lab(self) -> None:
        """Authenticate to the user's JupyterLab.

        Request the top-level lab page, which will force the OpenID Connect
        authentication with JupyterHub and set authentication cookies. This
        will be done implicitly the first time, but for long-running clients,
        you may need to do this periodically to refresh credentials.

        Raises
        ------
        JupyterProtocolError
            Raised if no ``_xsrf`` cookie was set in the reply from the lab.
        """
        route = f"user/{self.username}/lab"
        await self._client.get(route, fetch_mode="navigate")

    @_convert_exception
    async def is_lab_stopped(self, *, log_running: bool = False) -> bool:
        """Determine if the lab is fully stopped.

        Parameters
        ----------
        log_running
            Log a warning with additional information if the lab still
            exists.
        """
        route = f"hub/api/users/{self.username}"
        r = await self._client.get(route, add_referer=True)

        # We currently only support a single lab per user, so the lab is
        # running if and only if the server data for the user is not empty.
        data = r.json()
        result = data["servers"] == {}
        if log_running and not result:
            msg = "User API data still shows running lab"
            self._logger.warning(msg, servers=data["servers"])
        return result

    def open_lab_session(
        self,
        notebook_name: str | None = None,
        *,
        max_websocket_size: int | None = None,
        kernel_name: str = "LSST",
    ) -> JupyterLabSession:
        """Open a Jupyter lab session.

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
        max_websocket_size
            Maximum size of a WebSocket message, or `None` for no limit.
        kernel_name
            Name of the kernel to use for the session.

        Returns
        -------
        JupyterLabSession
            Context manager to open the WebSocket session.
        """
        return JupyterLabSession(
            username=self.username,
            jupyter_client=self._client,
            kernel_name=kernel_name,
            notebook_name=notebook_name,
            max_websocket_size=max_websocket_size,
            logger=self._logger,
        )

    @_convert_exception
    async def spawn_lab(self, config: NubladoImage) -> None:
        """Spawn a Jupyter lab pod.

        Parameters
        ----------
        config
            Image configuration.

        Raises
        ------
        JupyterWebError
            Raised if an error occurred talking to JupyterHub.
        """
        data = config.to_spawn_form()

        # Retrieving the spawn page before POSTing to it appears to trigger
        # some necessary internal state construction (and also more accurately
        # simulates a user interaction). See DM-23864.
        await self._client.get("hub/spawn", fetch_mode="navigate")

        # POST the options form to the spawn page. This should redirect to
        # the spawn-pending page, which will return a 200.
        self._logger.info("Spawning lab", user=self.username)
        await self._client.post("hub/spawn", data=data)

    @_convert_exception
    async def stop_lab(self) -> None:
        """Stop the user's Jupyter lab."""
        if await self.is_lab_stopped():
            self._logger.info("Lab is already stopped")
            return
        route = f"hub/api/users/{self.username}/server"
        self._logger.info("Stopping lab", user=self.username)
        await self._client.delete(route, add_referer=True)

    @_convert_generator_exception
    async def watch_spawn_progress(
        self,
    ) -> AsyncGenerator[SpawnProgressMessage]:
        """Monitor lab spawn progress.

        This is an EventStream API, which provides a stream of events until
        the lab is spawned or the spawn fails.

        Yields
        ------
        SpawnProgressMessage
            Next progress message from JupyterHub.
        """
        route = f"hub/api/users/{self.username}/server/progress"
        while True:
            stream_manager = await self._client.open_sse_stream(route)
            async with stream_manager as stream:
                progress = aiter(JupyterSpawnProgress(stream, self._logger))
                async with aclosing(progress):
                    async for message in progress:
                        yield message

            # Sometimes we get only the initial request message and then the
            # progress API immediately closes the connection. If that happens,
            # try reconnecting to the progress stream after a short delay.  I
            # believe this was a bug in kubespawner, so once we've switched to
            # the lab controller everywhere, we can probably drop this code.
            if message.progress > 0:
                break
            await asyncio.sleep(1)
            self._logger.info("Retrying spawn progress request")

    def _build_jupyter_client(self) -> JupyterAsyncClient:
        """Construct a new HTTP client to talk to Jupyter."""
        return JupyterAsyncClient(
            discovery_client=self._discovery,
            logger=self._logger,
            timeout=self._timeout,
            token=self._token,
            username=self.username,
        )
