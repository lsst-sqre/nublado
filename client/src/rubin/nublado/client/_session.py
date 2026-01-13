"""JupyterLab session management."""

from __future__ import annotations

import json
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Literal
from uuid import uuid4

from structlog.stdlib import BoundLogger
from websockets.asyncio.client import ClientConnection
from websockets.exceptions import WebSocketException

from ._asyncio import aclosing_iter
from ._exceptions import (
    NubladoExecutionError,
    NubladoTimeoutError,
    NubladoWebError,
    NubladoWebSocketError,
)
from ._http import JupyterAsyncClient
from ._models import CodeContext

__all__ = ["JupyterLabSession", "JupyterLabSessionManager"]


@dataclass(frozen=True, slots=True)
class _JupyterOutput:
    """Output from a Jupyter lab kernel.

    Parsing WebSocket messages will result in a stream of these objects with
    partial output, ending in a final one with the ``done`` flag set.
    """

    content: str
    """Partial output from code execution (may be empty)."""

    done: bool = False
    """Whether this indicates the end of execution."""


class JupyterLabSession:
    """Open WebSocket session to a JupyterLab.

    Objects of this type should be created via the `JupyterLabSessionManager`
    context manager.

    Parameters
    ----------
    username
        User the session is for.
    session_id
        Session ID of the JupyterLab session.
    socket
        Open WebSocket connection.
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
        session_id: str,
        socket: ClientConnection,
        logger: BoundLogger,
    ) -> None:
        self._username = username
        self._session_id = session_id
        self._socket = socket
        self._logger = logger

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
        NubladoDiscoveryError
            Raised if Nublado is missing from service discovery.
        NubladoExecutionError
            Raised if an error was reported by the Jupyter lab kernel.
        NubladoRedirectError
            Raised if the URL is outside of Nublado's URL space.
        NubladoWebSocketError
            Raised if there was a WebSocket protocol error while running code
            or waiting for the response.
        rubin.repertoire.RepertoireError
            Raised if there was an error talking to service discovery.
        RuntimeError
            Raised if called before entering the context and thus before
            creating the WebSocket session.

        Notes
        -----
        The output returned is only what the cell prints (its standard
        output). When run inside Jupyter, the cell will display the result of
        the last Python code line run. This parser ignores that information
        (the ``execute_result`` message).

        ``display_data`` is also ignored. This is the message type sent for
        other types of output, such as when you ask Bokeh to show a figure.
        It's a bunch of Javascript that will be interpreted by your browser.

        See the `JupyterLab wire protocol`_ for the full protocol. What we use
        is half a layer above that. We care what some messages on the various
        channels are, but not about the low-level implementation details of
        how those channels are established over ZMQ, for instance.
        """
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
            async with aclosing_iter(aiter(self._socket)) as messages:
                async for message in messages:
                    try:
                        output = self._parse_message(message, message_id)
                    except NubladoExecutionError:
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
        except NubladoExecutionError as e:
            e.code = code
            e.started_at = start
            if context:
                e.context = context
            raise
        except WebSocketException as e:
            exc = NubladoWebSocketError.from_exception(e, self._username)
            exc.started_at = start
            if context:
                exc.context = context
            raise exc from e

        # Return the accumulated output.
        return result

    def _parse_message(
        self, message: str | bytes, message_id: str
    ) -> _JupyterOutput | None:
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
        _JupyterOutput or None
            Parsed message, or `None` if the message wasn't of interest.

        Raises
        ------
        KeyError
            Raised if the WebSocket message wasn't in the expected format.
        NubladoExecutionError
            Raised if code execution fails.
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
        if msg_type in self._IGNORED_MESSAGE_TYPES:
            return None
        elif msg_type == "stream":
            return _JupyterOutput(content=data["content"]["text"])
        elif msg_type == "execute_reply":
            status = data["content"]["status"]
            if status == "ok":
                return _JupyterOutput(content="", done=True)
            else:
                raise NubladoExecutionError(self._username, status=status)
        elif msg_type == "error":
            error = "".join(data["content"]["traceback"])
            raise NubladoExecutionError(user=self._username, error=error)
        else:
            msg = "Ignoring unrecognized WebSocket message"
            self._logger.warning(msg, message_type=msg_type, message=data)
            return None


class JupyterLabSessionManager:
    """Manage JupyterLab sessions.

    A context manager providing an open WebSocket session. The session will be
    automatically deleted when exiting the context manager. Objects of this
    type should be created by calling `NubladoClient.lab_session`.

    Parameters
    ----------
    username
        User the session is for.
    jupyter_client
        HTTP client used to talk to JupyterLab.
    kernel_name
        Name of the kernel to use for the session.
    notebook_name
        Name of the notebook we will be running, which is passed to the
        session and might influence logging on the lab side. If set, the
        session type will be set to ``notebook``. If not set, the session type
        will be set to ``console``.
    max_websocket_size
        Maximum size of a WebSocket message to allow.
    websocket_open_timeout
        Timeout for opening a WebSocket.
    logger
        Logger to use.
    """

    def __init__(
        self,
        *,
        username: str,
        jupyter_client: JupyterAsyncClient,
        kernel_name: str = "lsst",
        notebook_name: str | None = None,
        max_websocket_size: int | None,
        websocket_open_timeout: timedelta = timedelta(seconds=60),
        logger: BoundLogger,
    ) -> None:
        self._username = username
        self._client = jupyter_client
        self._kernel_name = kernel_name
        self._notebook = notebook_name
        self._max_websocket_size = max_websocket_size
        self._websocket_open_timeout = websocket_open_timeout
        self._logger = logger

        self._session_id: str | None = None
        self._session: AbstractAsyncContextManager[ClientConnection] | None
        self._session = None
        self._socket: ClientConnection | None = None

    async def __aenter__(self) -> JupyterLabSession:
        """Create the session and open the WebSocket connection."""
        username = self._username
        start = datetime.now(tz=UTC)

        # Create the kernel.
        r = await self._client.post(
            f"user/{username}/api/sessions",
            json={
                "kernel": {"name": self._kernel_name},
                "name": self._notebook or "(no notebook)",
                "path": self._notebook if self._notebook else uuid4().hex,
                "type": "notebook" if self._notebook else "console",
            },
        )
        response = r.json()
        self._session_id = response["id"]
        kernel = response["kernel"]["id"]

        # Open a WebSocket to the now-running kernel.
        #
        # This class implements an explicit context manager instead of using
        # an async generator and contextlib.asynccontextmanager, and similarly
        # explicitly calls the __aenter__ and __aexit__ methods in the
        # WebSocket library rather than using it as a context manager.
        #
        # Initially, it was implemented as a generator, but when using that
        # approach the code after the yield in the generator was called at an
        # arbitrary time in the future, rather than when the context manager
        # exited. This meant that it was often called after the HTTPX client
        # had been closed, which meant it was unable to delete the lab session
        # and raised background exceptions. This approach allows more explicit
        # control of when the context manager is shut down and ensures it
        # happens immediately when the context exits.
        route = f"user/{username}/api/kernels/{kernel}/channels"
        start = datetime.now(tz=UTC)
        self._logger.debug("Opening WebSocket connection")
        try:
            self._session = await self._client.open_websocket(
                route,
                open_timeout=self._websocket_open_timeout,
                max_size=self._max_websocket_size,
            )
            self._socket = await self._session.__aenter__()
            return JupyterLabSession(
                username=username,
                session_id=self._session_id,
                socket=self._socket,
                logger=self._logger,
            )
        except WebSocketException as e:
            exc = NubladoWebSocketError.from_exception(e, username)
            exc.started_at = start
            raise exc from e
        except TimeoutError as e:
            msg = "Timed out attempting to open WebSocket to lab session"
            raise NubladoTimeoutError(msg, username, started_at=start) from e

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> Literal[False]:
        """Shut down the open WebSocket and delete the session."""
        if not self._session_id:
            return False
        start = datetime.now(tz=UTC)
        route = f"user/{self._username}/api/sessions/{self._session_id}"

        # Be careful to not raise an exception if we're already processing an
        # exception, since the exception from inside the context manager is
        # almost certainly more interesting than the exception from closing
        # the lab session.
        try:
            if self._session:
                await self._session.__aexit__(exc_type, exc_val, exc_tb)
            self._session = None
            self._socket = None
            await self._client.delete(route)
        except NubladoWebError:
            if exc_type:
                self._logger.exception("Failed to close session")
            else:
                raise
        except WebSocketException as e:
            if exc_type:
                self._logger.exception("Failed to close WebSocket")
            else:
                exc = NubladoWebSocketError.from_exception(e, self._username)
                exc.started_at = start
                raise exc from e

        return False
