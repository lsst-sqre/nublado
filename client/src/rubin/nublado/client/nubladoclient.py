"""Client for communicating with Jupyter using the RSP Notebook Aspect.

Allows the caller to login to JupyterHub, spawn lab containers, and then run
Jupyter kernels remotely.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Coroutine
from datetime import timedelta
from functools import wraps
from pathlib import Path
from types import TracebackType
from typing import Concatenate, Literal, ParamSpec, Self, TypeVar
from urllib.parse import urljoin, urlparse
from uuid import uuid4

import httpx
import structlog
from httpx import AsyncClient, Cookies, HTTPError, Response
from httpx_sse import EventSource, aconnect_sse
from safir.datetime import current_datetime
from structlog.stdlib import BoundLogger
from websockets.client import WebSocketClientProtocol
from websockets.client import connect as websocket_connect
from websockets.exceptions import WebSocketException

from ._constants import WEBSOCKET_OPEN_TIMEOUT
from ._util import source_list_by_cell
from .exceptions import (
    CodeExecutionError,
    ExecutionAPIError,
    JupyterProtocolError,
    JupyterTimeoutError,
    JupyterWebError,
    JupyterWebSocketError,
    NubladoClientSlackException,
)
from .models import (
    CodeContext,
    JupyterOutput,
    NotebookExecutionResult,
    NubladoImage,
    SpawnProgressMessage,
    User,
)

P = ParamSpec("P")
T = TypeVar("T")

__all__ = ["NubladoClient", "JupyterLabSession"]


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
        self._start = current_datetime(microseconds=True)

    async def __aiter__(self) -> AsyncIterator[SpawnProgressMessage]:
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
        async for sse in self._source.aiter_sse():
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
            now = current_datetime(microseconds=True)
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
        Base URL for talking to JupyterHub or the lab (via the proxy).
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
        base_url: str,
        kernel_name: str = "LSST",
        notebook_name: str | None = None,
        hub_route: str = "/nb",
        max_websocket_size: int | None,
        http_client: AsyncClient,
        xsrf: str | None,
        logger: BoundLogger,
    ) -> None:
        self._username = username
        self._base_url = base_url
        self._kernel_name = kernel_name
        self._notebook_name = notebook_name
        self._hub_route = hub_route
        self._max_websocket_size = max_websocket_size
        self._client = http_client
        self._xsrf = xsrf
        self._logger = logger

        self._session_id: str | None = None
        self._socket: WebSocketClientProtocol | None = None

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
        username = self._username
        notebook = self._notebook_name
        url = self._url_for(f"user/{username}/api/sessions")
        body = {
            "kernel": {"name": self._kernel_name},
            "name": notebook or "(no notebook)",
            "path": notebook if notebook else uuid4().hex,
            "type": "notebook" if notebook else "console",
        }
        headers = {}
        if self._xsrf:
            headers["X-XSRFToken"] = self._xsrf
        start = current_datetime(microseconds=True)
        try:
            r = await self._client.post(url, json=body, headers=headers)
            r.raise_for_status()
        except HTTPError as e:
            raise JupyterWebError.raise_from_exception_with_started_at(
                e, self._username, start
            ) from e
        response = r.json()
        self._session_id = response["id"]
        kernel = response["kernel"]["id"]

        # Build a request for the same URL using httpx so that it will
        # generate request headers, and copy select headers required for
        # authentication into the WebSocket call.
        url = self._url_for(f"user/{username}/api/kernels/{kernel}/channels")
        request = self._client.build_request("GET", url)
        headers = {h: request.headers[h] for h in ("authorization", "cookie")}
        if self._xsrf:
            headers["X-XSRFToken"] = self._xsrf

        # Open the WebSocket connection using those headers.
        self._logger.debug("Opening WebSocket connection")
        start = current_datetime(microseconds=True)
        try:
            self._socket = await websocket_connect(
                self._url_for_websocket(url),
                extra_headers=headers,
                open_timeout=WEBSOCKET_OPEN_TIMEOUT,
                max_size=self._max_websocket_size,
            ).__aenter__()
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
        if self._socket:
            start = current_datetime(microseconds=True)
            try:
                await self._socket.close()
            except WebSocketException as e:
                raise JupyterWebSocketError.from_exception(
                    e, username, started_at=start
                ) from e
            self._socket = None

        # Delete the lab session.
        url = self._url_for(f"user/{username}/api/sessions/{session_id}")
        headers = {}
        if self._xsrf:
            headers["X-XSRFToken"] = self._xsrf
        try:
            r = await self._client.delete(url, headers=headers)
            r.raise_for_status()
        except HTTPError as e:
            # Be careful to not raise an exception if we're already processing
            # an exception, since the exception from inside the context
            # manager is almost certainly more interesting than the exception
            # from closing the lab session.
            if exc_type:
                self._logger.exception("Failed to close session")
            else:
                start = current_datetime(microseconds=True)
                raise JupyterWebError.raise_from_exception_with_started_at(
                    e, self._username, start
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
        start = current_datetime(microseconds=True)
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
            async for message in self._socket:
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

                # Accumulate the results if they are of interest, and exit and
                # return the results if this message indicated the end of
                # execution.
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
        nb_url_path = str(notebook)
        url = self._url_for(f"user/{self._username}/files/{nb_url_path}")
        self._logger.debug(f"Getting content from {url}")
        resp = await self._client.get(url)
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
            str_path = str(path)
            url = self._url_for(f"user/{self._username}/files/{str_path}")
            self._logger.debug(f"Getting content from {url}")
            resp = await self._client.get(url)
            if resp.status_code == 200:
                content = resp.text
        if not content:
            raise JupyterWebError(
                "No notebook content to execute", user=self._username
            )
        exec_url = self._url_for(f"user/{self._username}/rubin/execution")
        try:
            start = current_datetime(microseconds=True)
            # The timeout is designed to catch issues connecting to JupyterLab
            # but to wait as long as possible for the notebook itself
            # to execute.
            headers: dict[str, str] = {}
            headers.update(self._client.headers)
            if self._xsrf:
                headers["X-XSRFToken"] = self._xsrf
            r = await self._client.post(
                exec_url,
                content=content,
                headers=headers,
                timeout=httpx.Timeout(5.0, read=None),
            )
            r.raise_for_status()
        except httpx.ReadTimeout as e:
            raise ExecutionAPIError(
                url=exec_url,
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
                url=exec_url,
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
        start = current_datetime(microseconds=True)
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

    def _url_for(self, partial: str) -> str:
        """Construct a JupyterHub or Jupyter lab URL from a partial URL.

        Parameters
        ----------
        partial
            Part of the URL after the prefix for JupyterHub.

        Returns
        -------
        str
            Full URL to use.
        """
        hub_base = urljoin(self._base_url, self._hub_route)
        if hub_base.endswith("/"):
            return f"{hub_base}{partial}"
        else:
            return f"{hub_base}/{partial}"

    def _url_for_websocket(self, url: str) -> str:
        """Convert a URL to a WebSocket URL.

        Parameters
        ----------
        url
            Regular HTTP URL.

        Returns
        -------
        str
            URL converted to the ``wss`` scheme.
        """
        return urlparse(url)._replace(scheme="wss").geturl()


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


def _convert_exception(
    f: Callable[Concatenate[NubladoClient, P], Coroutine[None, None, T]],
) -> Callable[Concatenate[NubladoClient, P], Coroutine[None, None, T]]:
    """Convert web error to `~rubin.nublado.client.exceptions.JupyterWebError`.

    This can only be used as a decorator on `JupyterClientSession` or another
    object that has a ``user`` property containing an
    `~rubin.nublado.client.models.user.User`.
    """

    @wraps(f)
    async def wrapper(
        client: NubladoClient, *args: P.args, **kwargs: P.kwargs
    ) -> T:
        start = current_datetime(microseconds=True)
        try:
            return await f(client, *args, **kwargs)
        except HTTPError as e:
            username = client.user.username
            raise JupyterWebError.raise_from_exception_with_started_at(
                e, username, start
            ) from e

    return wrapper


def _convert_iterator_exception(
    f: Callable[Concatenate[NubladoClient, P], AsyncIterator[T]],
) -> Callable[Concatenate[NubladoClient, P], AsyncIterator[T]]:
    """Convert web errors to a `~rubin.nublado.client.JupyterWebError`.

    This can only be used as a decorator on `JupyterClientSession` or another
    object that has a ``user`` property containing an
    `~rubin.nublado.client.models.user.User`.
    """

    @wraps(f)
    async def wrapper(
        client: NubladoClient, *args: P.args, **kwargs: P.kwargs
    ) -> AsyncIterator[T]:
        start = current_datetime(microseconds=True)
        try:
            async for result in f(client, *args, **kwargs):
                yield result
        except HTTPError as e:
            username = client.user.username
            raise JupyterWebError.raise_from_exception_with_started_at(
                e, username, start
            ) from e

    return wrapper


class NubladoClient:
    """Client for talking to JupyterHub and Jupyter labs that use Nublado.

    Parameters
    ----------
    user
        User as which to authenticate.
    base_url
        Base URL for JupyterHub and the proxy to talk to the labs.
    logger
        Logger to use (optional)
    timeout
        Timeout to use when talking to JupyterHub and Jupyter lab. This is
        used as a connection, read, and write timeout for all regular HTTP
        calls.

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
        user: User,
        base_url: str,
        hub_route: str = "/nb",
        logger: BoundLogger | None = None,
        timeout: timedelta = timedelta(seconds=30),
    ) -> None:
        self.user = user
        self._base_url = base_url
        self._hub_route = hub_route
        if logger is None:
            logger = structlog.get_logger()
        self._logger = logger

        # Construct a connection pool to use for requests to JupyterHub. We
        # have to create a separate connection pool for every user, since
        # each will get user-specific cookies set by JupyterHub. If we shared
        # connection pools, users would overwrite each other's cookies and
        # get authentication failures from labs.
        headers = {"Authorization": f"Bearer {user.token}"}
        self._client = AsyncClient(
            follow_redirects=True,
            base_url=base_url,
            headers=headers,
            timeout=timeout.total_seconds(),
        )
        self._hub_xsrf: str | None = None
        self._lab_xsrf: str | None = None
        self._logger.debug("Created new NubladoClient")

    async def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        await self._client.aclose()

    @property
    def http(self) -> AsyncClient:
        return self._client

    @property
    def lab_xsrf(self) -> str | None:
        return self._lab_xsrf

    @property
    def hub_xsrf(self) -> str | None:
        return self._hub_xsrf

    @_convert_exception
    async def auth_to_hub(self) -> None:
        """Retrieve the JupyterHub home page.

        This forces a refresh of the authentication cookies set in the client
        session, which may be required to use API calls that return 401 errors
        instead of redirecting the user to log in.

        The reply will set an ``_xsrf`` cookie that must be lifted into the
        headers for subsequent requests.

        Raises
        ------
        JupyterProtocolError
            Raised if no ``_xsrf`` cookie was set in the reply from the lab.
        """
        url = self._url_for("hub/home")
        r = await self._client.get(url, follow_redirects=False)
        # As with auth_to_lab, manually extract from cookies at each
        # redirection, because httpx doesn't do that if following redirects
        # automatically.
        while r.is_redirect:
            self._logger.debug(
                "Following hub redirect looking for _xsrf cookies",
                method=r.request.method,
                url=r.url.copy_with(query=None, fragment=None),
                status_code=r.status_code,
            )
            xsrf = self._extract_xsrf(r)
            if xsrf and xsrf != self._hub_xsrf:
                self._hub_xsrf = xsrf
                self._logger.debug(
                    "Set _hub_xsrf",
                    url=r.url.copy_with(query=None, fragment=None),
                    status_code=r.status_code,
                )
            next_url = urljoin(url, r.headers["Location"])
            r = await self._client.get(next_url, follow_redirects=False)
        r.raise_for_status()
        xsrf = self._extract_xsrf(r)
        if xsrf and xsrf != self._hub_xsrf:
            self._hub_xsrf = xsrf
            self._logger.debug(
                "Set _hub_xsrf",
                url=r.url.copy_with(query=None, fragment=None),
                status_code=r.status_code,
            )
        elif not self._hub_xsrf:
            msg = "No _xsrf cookie set in login reply from JupyterHub"
            raise JupyterProtocolError(msg)

    @_convert_exception
    async def auth_to_lab(self) -> None:
        """Authenticate to the Jupyter lab.

        Request the top-level lab page, which will force the OpenID Connect
        authentication with JupyterHub and set authentication cookies. This is
        required before making API calls to the lab, such as running code.

        The reply will set an ``_xsrf`` cookie that must be lifted into the
        headers for subsequent requests.

        Setting ``Sec-Fetch-Mode`` is not currently required, but it
        suppresses an annoying error message in the lab logs.

        Raises
        ------
        JupyterProtocolError
            Raised if no ``_xsrf`` cookie was set in the reply from the lab.
        """
        url = self._url_for(f"user/{self.user.username}/lab")
        headers = {"Sec-Fetch-Mode": "navigate"}
        r = await self._client.get(
            url, headers=headers, follow_redirects=False
        )
        while r.is_redirect:
            self._logger.debug(
                "Following lab redirect looking for _xsrf cookies",
                method=r.request.method,
                url=r.url.copy_with(query=None, fragment=None),
                status_code=r.status_code,
            )
            xsrf = self._extract_xsrf(r)
            if xsrf and xsrf != self._lab_xsrf:
                self._lab_xsrf = xsrf
                self._logger.debug(
                    "Set _lab_xsrf",
                    url=r.url.copy_with(query=None, fragment=None),
                    status_code=r.status_code,
                )
            next_url = urljoin(url, r.headers["Location"])
            r = await self._client.get(
                next_url, headers=headers, follow_redirects=False
            )
        r.raise_for_status()
        xsrf = self._extract_xsrf(r)
        if xsrf and xsrf != self._lab_xsrf:
            self._lab_xsrf = xsrf
            self._logger.debug(
                "Set _lab_xsrf",
                url=r.url.copy_with(query=None, fragment=None),
                status_code=r.status_code,
            )
        if not self._lab_xsrf:
            msg = "No _xsrf cookie set in login reply from lab"
            raise JupyterProtocolError(msg)

    @_convert_exception
    async def is_lab_stopped(self, *, log_running: bool = False) -> bool:
        """Determine if the lab is fully stopped.

        Parameters
        ----------
        log_running
            Log a warning with additional information if the lab still
            exists.
        """
        url = self._url_for(f"hub/api/users/{self.user.username}")
        headers = {"Referer": self._url_for("hub/home")}
        if self._hub_xsrf:
            headers["X-XSRFToken"] = self._hub_xsrf
        r = await self._client.get(url, headers=headers)
        r.raise_for_status()

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
            username=self.user.username,
            base_url=self._base_url,
            kernel_name=kernel_name,
            notebook_name=notebook_name,
            max_websocket_size=max_websocket_size,
            http_client=self._client,
            xsrf=self._lab_xsrf,
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
        url = self._url_for("hub/spawn")
        data = config.to_spawn_form()

        # Retrieving the spawn page before POSTing to it appears to trigger
        # some necessary internal state construction (and also more accurately
        # simulates a user interaction). See DM-23864.
        headers = {}
        if self._hub_xsrf:
            headers["X-XSRFToken"] = self._hub_xsrf
        r = await self._client.get(url, headers=headers)
        r.raise_for_status()

        # POST the options form to the spawn page. This should redirect to
        # the spawn-pending page, which will return a 200.
        self._logger.info("Spawning lab image", user=self.user.username)
        r = await self._client.post(url, headers=headers, data=data)
        r.raise_for_status()

    @_convert_exception
    async def stop_lab(self) -> None:
        """Stop the user's Jupyter lab."""
        if await self.is_lab_stopped():
            self._logger.info("Lab is already stopped")
            return
        url = self._url_for(f"hub/api/users/{self.user.username}/server")
        headers = {"Referer": self._url_for("hub/home")}
        if self._hub_xsrf:
            headers["X-XSRFToken"] = self._hub_xsrf
        r = await self._client.delete(url, headers=headers)
        r.raise_for_status()

    @_convert_iterator_exception
    async def watch_spawn_progress(
        self,
    ) -> AsyncIterator[SpawnProgressMessage]:
        """Monitor lab spawn progress.

        This is an EventStream API, which provides a stream of events until
        the lab is spawned or the spawn fails.

        Yields
        ------
        SpawnProgressMessage
            Next progress message from JupyterHub.
        """
        client = self._client
        username = self.user.username
        url = self._url_for(f"hub/api/users/{username}/server/progress")
        headers = {
            "Referer": self._url_for("hub/home"),
        }
        if self._hub_xsrf:
            headers["X-XSRFToken"] = self._hub_xsrf
        while True:
            async with aconnect_sse(client, "GET", url, headers=headers) as s:
                async for message in JupyterSpawnProgress(s, self._logger):
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

    def _extract_xsrf(self, response: Response) -> str | None:
        """Extract the XSRF token from the cookies in a response.

        Parameters
        ----------
        response
            Response from a Jupyter server.

        Returns
        -------
        str or None
            Extracted XSRF value or `None` if none was present.
        """
        cookies = Cookies()
        cookies.extract_cookies(response)
        xsrf = cookies.get("_xsrf")
        if xsrf is not None:
            self._logger.debug(
                "Extracted _xsrf cookie",
                method=response.request.method,
                url=response.url.copy_with(query=None, fragment=None),
                status_code=response.status_code,
                # Logging the set-cookie header can be useful here but it
                # leaks secrets.  Don't put that code in a release build.
            )
        return xsrf

    def _url_for(self, partial: str) -> str:
        """Construct a JupyterHub or Jupyter lab URL from a partial URL.

        Parameters
        ----------
        partial
            Part of the URL after the prefix for JupyterHub.

        Returns
        -------
        str
            Full URL to use.
        """
        hub_base = urljoin(self._base_url, self._hub_route)
        if hub_base.endswith("/"):
            return f"{hub_base}{partial}"
        else:
            return f"{hub_base}/{partial}"

    def _url_for_lab_websocket(self, username: str, kernel: str) -> str:
        """Build the URL for the WebSocket to a lab kernel."""
        url = self._url_for(f"user/{username}/api/kernels/{kernel}/channels")
        return urlparse(url)._replace(scheme="wss").geturl()
