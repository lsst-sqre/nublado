"""A mock JupyterHub and lab for tests."""

from __future__ import annotations

import asyncio
import json
import os
import re
from base64 import urlsafe_b64decode, urlsafe_b64encode
from collections import defaultdict
from collections.abc import (
    AsyncGenerator,
    AsyncIterator,
    Callable,
    Coroutine,
    Iterable,
)
from contextlib import asynccontextmanager, redirect_stdout
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from functools import wraps
from io import StringIO
from re import Pattern
from traceback import format_exc
from typing import Any
from unittest.mock import ANY, patch
from urllib.parse import parse_qs, urljoin, urlparse
from uuid import uuid4

import respx
import websockets
from httpx import URL, Request, Response
from rubin.repertoire import DiscoveryClient

from ._models import NotebookExecutionResult
from ._util import normalize_source

__all__ = [
    "MockJupyter",
    "MockJupyterAction",
    "MockJupyterLabSession",
    "MockJupyterState",
    "register_mock_jupyter",
]


class MockJupyterAction(Enum):
    """Possible actions on the Jupyter lab state machine."""

    LOGIN = "login"
    HOME = "home"
    HUB = "hub"
    USER = "user"
    PROGRESS = "progress"
    SPAWN = "spawn"
    SPAWN_PENDING = "spawn_pending"
    LAB = "lab"
    DELETE_LAB = "delete_lab"
    CREATE_SESSION = "create_session"
    DELETE_SESSION = "delete_session"


@dataclass
class MockJupyterLabSession:
    """Metadata for an open Jupyter lab session."""

    kernel_name: str
    """Name of the kernel requested by the client."""

    name: str
    """Name of the session from the client."""

    path: str
    """Path of the session from the client."""

    type: str
    """Type of the session from the client."""

    session_id: str = field(default_factory=lambda: uuid4().hex)
    """Session ID."""

    kernel_id: str = field(default_factory=lambda: uuid4().hex)
    """Requested kernel."""


class MockJupyterState(Enum):
    """Possible states the Jupyter lab can be in."""

    LOGGED_OUT = "logged out"
    LOGGED_IN = "logged in"
    SPAWN_PENDING = "spawn pending"
    LAB_RUNNING = "lab running"


type _MockHandler = Callable[
    [MockJupyter, Request, str], Coroutine[None, None, Response]
]
"""Type of a handler for a mocked Jupyter call."""

type _MockRequiredState = MockJupyterState | Iterable[MockJupyterState]
"""Type of a specification for required state."""

type _MockSideEffect = Callable[
    [MockJupyter, Request], Coroutine[None, None, Response]
]
"""Type of a respx mock side effect function."""


class MockJupyter:
    """A mock Jupyter state machine.

    This should be invoked via mocked HTTP calls so that tests can simulate
    making REST calls to the real JupyterHub and Lab. It simulates the process
    of spawning a lab, creating a session, and running code within that
    session.

    It also has two result registration methods, ``register_python_result``
    and ``register_extension_result``. These allow you to mock responses for
    specific Python inputs that would be executed in the running Lab, so that
    you do not need to replicate the target environment in your test suite.

    If the username is provided in ``X-Auth-Request-User`` in the request
    headers, that name will be used. This will be the case when the mock is
    behind something emulating a GafaelfawrIngress, and is how the actual Hub
    would be called. If it is not, an ``Authorization`` header of the form
    ``Bearer <token>`` will be expected, and the username will be taken to be
    the portion after ``gt-`` and before the first period.

    Parameters
    ----------
    base_url
        Base URL at which to install the Jupyter mocks.
    use_subdomains
        If `True`, simulate per-user subdomains. JupyterHub will use the URL
        :samp:`nb.{hostname}` where the hostname is taken from ``base_url``,
        and JupyterLab will use :samp:`{username}.nb.{hostname}`.
    """

    def __init__(self, base_url: str, *, use_subdomains: bool = True) -> None:
        self._base_url = URL(base_url)
        self._use_subdomains = use_subdomains

        self._hub_xsrf = os.urandom(8).hex()
        self._lab_xsrf = os.urandom(8).hex()

        self._code_results: dict[str, str | BaseException] = {}
        self._delete_at: dict[str, datetime | None] = {}
        self._delete_delay: timedelta | None = None
        self._fail: defaultdict[str, set[MockJupyterAction]] = defaultdict(set)
        self._lab_form: dict[str, dict[str, str]] = {}
        self._notebook_results: dict[str, NotebookExecutionResult] = {}
        self._redirect_loop = False
        self._sessions: dict[str, MockJupyterLabSession] = {}
        self._spawn_timeout = False
        self._state: dict[str, MockJupyterState] = {}

    @staticmethod
    def create_mock_token(username: str) -> str:
        """Create a mock Gafaelfawr token for the given user.

        Parameters
        ----------
        username
            Username for which to create a token.

        Returns
        -------
        str
            Mock token usable only with `MockJupyter` that will be considered
            a valid token for the given username.
        """
        encoded_username = urlsafe_b64encode(username.encode()).decode()
        return f"gt-{encoded_username}.{os.urandom(4).hex()}"

    def build_code_result(
        self, code: str, variables: dict[str, Any]
    ) -> str | None:
        """Get the execution results for a piece of code.

        Normally, this is only used by the JupyterLab WebSocket mock, but test
        suites can call it directly if they want to see what the mock would
        return for a given piece of code.

        .. warning::

           Code for which no result has been registered via
           `register_python_result` will be executed via `exec`. This mock
           therefore supports arbitrary code execution via its handlers and
           must never be exposed to untrusted messages.

        Parameters
        ----------
        code
            Code for which to retrieve or generate results.
        variables
            Dictionary holding global and local variables. This may be written
            to by the code, and the caller should keep passing the same
            dictionary if variable continuity across cell execution (emulating
            a real notebook) is desired.

        Returns
        -------
        str
            Corresponding results.

        Raises
        ------
        Exception
            Raised if there is no registered result for a given piece of code
            and the code produces an exception when run with `exec`, or if the
            registered code result is a `BaseException` object (which is then
            raised).
        """
        if result := self._code_results.get(code):
            if isinstance(result, BaseException):
                raise result
            return result

        # No registered result, so execute the code with exec.
        output = StringIO()
        with redirect_stdout(output):
            exec(code, variables)  # noqa: S102
        return output.getvalue()

    def fail(self, username: str, action: MockJupyterAction) -> None:
        """Configure the given action to fail for the given user.

        This can be used by test suites to test handling of Nublado failures
        at various calls in the process of executing code in a JupyterLab.

        Parameters
        ----------
        username
            Username for whom is action should fail.
        action
            An action on the mock Nublado that should fail.
        """
        self._fail[username].add(action)

    def get_last_spawn_form(self, username: str) -> dict[str, str] | None:
        """Get the contents of the last spawn form submitted for a user.

        Parameters
        ----------
        username
            Username of the user.

        Returns
        -------
        dict of str or None
            Key and value pairs submitted to the Nublado spawn form, or `None`
            if that user hasn't submitted a spawn form. Note that although a
            native Python parsing of a form submission will return a list of
            values for each key, this method checks that only one value is
            present for each key and then removes the list wrapper.
        """
        return self._lab_form.get(username)

    def get_session(self, username: str) -> MockJupyterLabSession | None:
        """Retrieve the currently active mock JupyterLab session for a user.

        Parameters
        ----------
        username
            Username of the user.

        Returns
        -------
        MockJupyterLabSession or None
            Current open JupyterLab session for that user, or `None` if none
            is open.
        """
        return self._sessions.get(username)

    def register_notebook_result(
        self, notebook: str, result: NotebookExecutionResult
    ) -> None:
        """Register the result of full notebook execution.

        Parameters
        ----------
        code
            Full notebook contents as a JSON-formatted string.
        result
            Results to return when that notebook is executed via the mock.
        """
        cache_key = normalize_source(notebook)
        self._notebook_results[cache_key] = result

    def register_python_result(
        self, code: str, result: str | BaseException
    ) -> None:
        """Register the expected cell output for a given source input.

        Whenever the given code is executed inside a JupyterLab session in the
        mock, the given result will be returned or, if it is an exception
        type, raised.

        Parameters
        ----------
        code
            Expected code block.
        result
            Result (standard output) of execution, or a `BaseException` object
            to raise that exception.
        """
        self._code_results[code] = result

    def set_delete_delay(self, delay: timedelta | None) -> None:
        """Set whether to delete labs immediately.

        By default, the mock deletes user labs immediately. Sometimes the
        caller may want to test handling of the lab shutdown. It can do that
        by calling this method on the mock and set a delay for how long it
        should take to delete a lab.

        Parameters
        ----------
        delay
            How long to wait before deleting the lab or `None` to not wait.
            The lab deletion will actually happen after this delay has passed
            and the client calls the mock route that returns the list of a
            user's current labs (called by
            `~rubin.nublado.client.NubladoClient.is_lab_stopped`).
        """
        self._delete_delay = delay

    def set_redirect_loop(self, *, enabled: bool) -> None:
        """Set whether to return an infinite redirect loop.

        If enabled, the endpoint for watching spawn progress will instead
        return an infinite redirect loop to the same URL.

        Parameters
        ----------
        enabled
            Whether to enable a redirect loop.
        """
        self._redirect_loop = enabled

    def set_spawn_timeout(self, *, enabled: bool) -> None:
        """Set whether to time out during lab spawn.

        If enabled, the endpoint for watching spawn progress will hang for
        60s and then return nothing.

        Parameters
        ----------
        enabled
            Whether to enable a spawn timeout.
        """
        self._spawn_timeout = enabled

    @staticmethod
    def _check(
        *,
        required_state: _MockRequiredState | None = None,
        url_format: str | None = None,
    ) -> Callable[[_MockHandler], _MockSideEffect]:
        """Wrap `MockJupyter` methods to perform common checks.

        There are various common checks that should be performed for every
        request to the mock, and the username always has to be extracted from
        the token and injected as an additional argument to the method. This
        wrapper performs those checks and then injects the username of the
        authenticated user into the underlying handler.

        Paramaters
        ----------
        required_state
            If given, the state or iterable of states that Jupyter must be in
            for this call to be valid.
        url_format
            A Python format string that, when expanded, must occur in the path
            of the URL. The ``{user}`` variable is expanded into the
            discovered username. This is used to check that the authentication
            credentials match the URL.

        Returns
        -------
        typing.Callable
            Decorator to wrap `MockJupyter` methods.

        Raises
        ------
        RuntimeError
            Raised if the URL path does not match the expected format.
        """

        def decorator(f: _MockHandler) -> _MockSideEffect:
            @wraps(f)
            async def wrapper(mock: MockJupyter, request: Request) -> Response:
                user = mock._get_user_from_headers(request)
                if user is None:
                    return Response(403, request=request)

                # If told to check the URL, verify it has the right path.
                if url_format:
                    path = url_format.format(user=user)
                    assert path in str(request.url), (
                        f"Path {path} not found in URL {request.url!s}"
                    )

                # If told to check state, verify it.
                if required_state:
                    state = mock._state.get(user, MockJupyterState.LOGGED_OUT)
                    if isinstance(required_state, MockJupyterState):
                        expected = {required_state}
                    else:
                        expected = set(required_state)
                    assert state in expected, (
                        f"Jupyter state {state!s} not in {expected!s}"
                    )

                # Handle any redirects needed by the multi-domain case.
                if redirect := mock._maybe_redirect(request, user):
                    headers = {"Location": redirect}
                    return Response(302, request=request, headers=headers)

                # All checks passed. Call the actual handler.
                return await f(mock, request, user)

            return wrapper

        return decorator

    # Below this point are the mock handler methods for the various routes.
    # None of these methods should normally be called directly by test code.
    # They are registered with respx and invoked automatically when a request
    # is sent by the code under test to the mocked JupyterHub or JupyterLab.

    @_check()
    async def login(self, request: Request, user: str) -> Response:
        if MockJupyterAction.LOGIN in self._fail[user]:
            return Response(500, request=request)
        state = self._state.get(user, MockJupyterState.LOGGED_OUT)
        if state == MockJupyterState.LOGGED_OUT:
            self._state[user] = MockJupyterState.LOGGED_IN
        xsrf = f"_xsrf={self._hub_xsrf}"
        return Response(200, request=request, headers={"Set-Cookie": xsrf})

    @_check(url_format="/hub/api/users/{user}")
    async def user(self, request: Request, user: str) -> Response:
        if MockJupyterAction.USER in self._fail[user]:
            return Response(500, request=request)
        self._check_xsrf(request)
        state = self._state.get(user, MockJupyterState.LOGGED_OUT)
        if state == MockJupyterState.SPAWN_PENDING:
            server = {"name": "", "pending": "spawn", "ready": False}
            body = {"name": user, "servers": {"": server}}
        elif state == MockJupyterState.LAB_RUNNING:
            server = {"name": "", "pending": None, "ready": True}
            if delete_at := self._delete_at.get(user):
                if datetime.now(tz=UTC) > delete_at:
                    del self._delete_at[user]
                    self._state[user] = MockJupyterState.LOGGED_IN
                else:
                    server = {"name": "", "pending": "delete", "ready": False}
            body = {"name": user, "servers": {"": server}}
        else:
            body = {"name": user, "servers": {}}
        return Response(200, json=body, request=request)

    @_check(
        required_state=(
            MockJupyterState.SPAWN_PENDING,
            MockJupyterState.LAB_RUNNING,
        ),
        url_format="/hub/api/users/{user}/server/progress",
    )
    async def progress(self, request: Request, user: str) -> Response:
        if self._redirect_loop:
            headers = {"Location": str(request.url)}
            return Response(303, headers=headers, request=request)
        state = self._state.get(user, MockJupyterState.LOGGED_OUT)
        if MockJupyterAction.PROGRESS in self._fail[user]:
            body = (
                'data: {"progress": 0, "message": "Server requested"}\n\n'
                'data: {"progress": 50, "message": "Spawning server..."}\n\n'
                'data: {"progress": 75, "message": "Spawn failed!"}\n\n'
            )
        elif state == MockJupyterState.LAB_RUNNING:
            body = (
                'data: {"progress": 100, "ready": true, "message": "Ready"}\n'
                "\n"
            )
        elif self._spawn_timeout:
            # Cause the spawn to time out by pausing for longer than the test
            # should run for and then returning nothing.
            await asyncio.sleep(60)
            body = ""
        else:
            self._state[user] = MockJupyterState.LAB_RUNNING
            body = (
                'data: {"progress": 0, "message": "Server requested"}\n\n'
                'data: {"progress": 50, "message": "Spawning server..."}\n\n'
                'data: {"progress": 100, "ready": true, "message": "Ready"}\n'
                "\n"
            )
        headers = {"Content-Type": "text/event-stream"}
        return Response(200, text=body, headers=headers, request=request)

    @_check(required_state=MockJupyterState.LOGGED_IN)
    async def spawn(self, request: Request, user: str) -> Response:
        if MockJupyterAction.SPAWN in self._fail[user]:
            return Response(500, request=request)
        self._check_xsrf(request)
        self._state[user] = MockJupyterState.SPAWN_PENDING
        self._lab_form[user] = {
            k: v[0] for k, v in parse_qs(request.content.decode()).items()
        }
        url = self._url(f"hub/spawn-pending/{user}")
        return Response(302, headers={"Location": url}, request=request)

    @_check(
        required_state=MockJupyterState.SPAWN_PENDING,
        url_format="/hub/spawn-pending/{user}",
    )
    async def spawn_pending(self, request: Request, user: str) -> Response:
        if MockJupyterAction.SPAWN_PENDING in self._fail[user]:
            return Response(500, request=request)
        self._check_xsrf(request)
        return Response(200, request=request)

    @_check(url_format="/hub/user/{user}/lab")
    async def missing_lab(self, request: Request, user: str) -> Response:
        return Response(503, request=request)

    @_check(url_format="/user/{user}/lab")
    async def lab(self, request: Request, user: str) -> Response:
        if MockJupyterAction.LAB in self._fail[user]:
            return Response(500, request=request)
        state = self._state.get(user, MockJupyterState.LOGGED_OUT)

        # In the running state, there should be another redirect to
        # /hub/api/oauth2/authorize, which doesn't set a cookie and then
        # redirects to /user/username/oauth_callback. We're skipping that one
        # because it doesn't change the client state at all.
        if state == MockJupyterState.LAB_RUNNING:
            headers = {
                "Location": self._url(f"user/{user}/oauth_callback"),
                "Set-Cookie": f"_xsrf={self._lab_xsrf}",
            }
            return Response(302, headers=headers, request=request)
        else:
            host = self._base_url.host
            headers = {"Location": self._url(f"hub/user/{user}/lab", host)}
            return Response(302, headers=headers, request=request)

    @_check(url_format="/user/{user}/oauth_callback")
    async def lab_callback(self, request: Request, user: str) -> Response:
        """Simulate returning to JupyterLab after authentication."""
        return Response(200, request=request)

    @_check(url_format="/hub/api/users/{user}/server")
    async def delete_lab(self, request: Request, user: str) -> Response:
        self._check_xsrf(request)
        if MockJupyterAction.DELETE_LAB in self._fail[user]:
            return Response(500, request=request)
        state = self._state.get(user, MockJupyterState.LOGGED_OUT)
        assert state != MockJupyterState.LOGGED_OUT, "User not authenticated"
        if not self._delete_delay:
            self._state[user] = MockJupyterState.LOGGED_IN
        else:
            self._delete_at[user] = datetime.now(tz=UTC) + self._delete_delay
        return Response(202, request=request)

    @_check(
        required_state=MockJupyterState.LAB_RUNNING,
        url_format="/user/{user}/api/sessions",
    )
    async def create_session(self, request: Request, user: str) -> Response:
        self._check_xsrf(request, is_lab_route=True)
        assert user not in self._sessions, "User has an existing session"
        if MockJupyterAction.CREATE_SESSION in self._fail[user]:
            return Response(500, request=request)
        body = json.loads(request.content.decode())
        assert body["kernel"].get("name")
        assert body.get("name")
        assert body.get("path")
        assert body.get("type") in ("console", "notebook")
        session = MockJupyterLabSession(
            kernel_name=body["kernel"]["name"],
            name=body["name"],
            path=body["path"],
            type=body["type"],
        )
        self._sessions[user] = session
        response = {
            "id": session.session_id,
            "kernel": {"id": session.kernel_id},
        }
        return Response(201, json=response, request=request)

    @_check(
        required_state=MockJupyterState.LAB_RUNNING,
        url_format="/user/{user}/api/sessions",
    )
    async def delete_session(self, request: Request, user: str) -> Response:
        session_id = self._sessions[user].session_id
        assert str(request.url).endswith(f"/{session_id}"), (
            f"Invalid session URL {request.url!s}"
        )
        self._check_xsrf(request, is_lab_route=True)
        if MockJupyterAction.DELETE_SESSION in self._fail[user]:
            return Response(500, request=request)
        del self._sessions[user]
        return Response(204, request=request)

    @_check(required_state=MockJupyterState.LAB_RUNNING)
    async def run_notebook(self, request: Request, user: str) -> Response:
        """Simulate the /rubin/execution endpoint.

        Notes
        -----
        This does not use the nbconvert/nbformat method of the actual
        endpoint, because installing kernels into what are already-running
        pythons in virtual evironments in the testing environment is nasty.

        First, we will try using the input notebook text as a key into a cache
        of registered responses (this is analogous to doing the same with
        registered responses to python snippets in the Session mock): if
        the key is present, then we will return the response that corresponds
        to that key.

        If not, we're just going to return the input notebook as if it ran
        without errors, but without updating any of its outputs or resources,
        or throwing an error.  This is not a a very good simulation.
        But since the whole point of this is to run a notebook in a particular
        kernel context, and for us that usually means the "LSST" kernel
        with the DM Pipelines Stack in it, that would be incredibly awful
        to use in a unit test context.  If you want to know if your
        notebook will really work, you're going to have to run it in the
        correct kernel, and the client unit tests are not the place for that.

        Much more likely is that you have a test notebook that should
        produce certain results in the wild.  In that case, you would
        register those results, and then the correct output would be
        delivered by the cache.
        """
        try:
            body = json.loads(request.content.decode())
            notebook = json.dumps(body["notebook"])
            resources = body["resources"]
        except Exception:
            notebook = request.content.decode()
            resources = {}
        if result := self._notebook_results.get(normalize_source(notebook)):
            result_json = result.model_dump()
        else:
            result_json = {
                "notebook": notebook,
                "resources": resources,
                "error": None,
            }
        return Response(200, json=result_json)

    def _check_xsrf(
        self, request: Request, *, is_lab_route: bool = False
    ) -> None:
        """Check whether the client sent the right XSRF header.

        Raises an assertion if the XSRF header is missing or incorrect.

        Parameters
        ----------
        request
            Incoming request.
        is_lab_route
            `True` if this is a JupyterLab route and should use the JupyterLab
            XSRF token, `False` if it should use the JupyterHub XSRF token.
        """
        xsrf = request.headers.get("x-xsrftoken")
        expected = self._lab_xsrf if is_lab_route else self._hub_xsrf
        assert xsrf == expected, f"XSRF mismatch: {xsrf} != {expected}"

    def _get_user_from_headers(self, request: Request) -> str | None:
        """Get the user from the request headers.

        If the username is provided in ``X-Auth-Request-User`` in the request
        headers, that name will be used. This will be the case when the mock
        is behind something emulating a GafaelfawrIngress, and is how the
        actual Hub would be called. If it is not, an ``Authorization`` header
        of the form ``bearer <token>`` will be expected, and the username will
        be taken to be the portion after ``gt-`` and before the first period.

        Parameters
        ----------
        request
            Incoming request.

        Returns
        -------
        str or None
            Authenticated username, or `None` if no authenticated user could
            be found.
        """
        authorization = request.headers.get("Authorization", None)
        if not authorization:
            return None
        if not authorization.lower().startswith("bearer "):
            return None
        token = authorization.split(" ", 1)[1]
        if not token.startswith("gt-"):
            return None
        try:
            return urlsafe_b64decode(token[3:].split(".", 1)[0]).decode()
        except Exception:
            return None

    def _maybe_redirect(self, request: Request, user: str) -> str | None:
        """Maybe redirect for user subdomains.

        If user subdomains are enabled, return the URL to which the user
        should be redirected.

        Parameters
        ----------
        request
            Incoming request to the mock.
        user
            Username parsed from the incoming headers.

        Returns
        -------
        str or None
            URL to which the user should be redirected if user subdomains are
            enabled and the request is not to the subdomain. Otherwise,
            `None`, indicating the user should not be redirected.
        """
        if not self._use_subdomains:
            return None
        host = request.url.host
        if f"user/{user}" in request.url.path and not host.startswith(user):
            return str(request.url.copy_with(host=f"{user}.{host}"))
        else:
            return None

    def _url(self, route: str, host: str | None = None) -> str:
        """Construct a URL for a redirect.

        Parameters
        ----------
        route
            Path portion of the redirect.
        host
            Host portion of the redirect, if one should be present.
        """
        path = self._base_url.path.rstrip("/") + f"/{route}"
        if host:
            url = self._base_url.copy_with(
                host=host, path=path, query=None, fragment=None
            )
            return str(url)
        else:
            return path


class MockJupyterWebSocket:
    """Simulate the WebSocket connection to a Jupyter Lab.

    Note
    ----
    The methods are named the reverse of what you would expect: ``send``
    receives and processes a message. This is because this is a mock of a
    client library but is simulating a server, so is operating in the reverse
    direction.
    """

    def __init__(
        self, username: str, session_id: str, parent: MockJupyter
    ) -> None:
        self._username = username
        self._session_id = session_id
        self._parent = parent

        # Header of the message sent to JupyterLab, which should therefore be
        # present in all responses.
        self._header: dict[str, str] | None = None

        # Code block currently being executed.
        self._code: str | None = None

        # Holds local and global variables across cell executions so that
        # notebook state between cells can be simulated.
        self._state: dict[str, Any] = {}

    async def close(self) -> None:
        """Simulate close of the WebSocket."""

    async def send(self, message_str: str) -> None:
        """Simulate sending a message to the JupyterLab WebSocket."""
        message = json.loads(message_str)
        expected = {
            "header": {
                "username": self._username,
                "version": "5.4",
                "session": self._session_id,
                "date": ANY,
                "msg_id": ANY,
                "msg_type": "execute_request",
            },
            "parent_header": {},
            "channel": "shell",
            "content": {
                "code": ANY,
                "silent": False,
                "store_history": False,
                "user_expressions": {},
                "allow_stdin": False,
            },
            "metadata": {},
            "buffers": {},
        }
        assert message == expected, (
            f"Unexpected WebSocket message: {message} != {expected}"
        )
        self._header = message["header"]
        self._code = message["content"]["code"]

    async def __aiter__(self) -> AsyncIterator[str]:
        """Simulate receiving messages from the JupyterLab WebSocket."""
        while True:
            assert self._header, "Read from WebSocket before sending message"
            response = self._build_response()
            yield json.dumps(response)

    def _build_response(self) -> dict[str, Any]:
        """Construct a response to a code execution request."""
        parent = self._parent
        if self._code:
            try:
                result = parent.build_code_result(self._code, self._state)
                self._code = None
                if isinstance(result, BaseException):
                    raise result
            except BaseException:
                response = {
                    "msg_type": "error",
                    "parent_header": self._header,
                    "content": {"traceback": format_exc()},
                }
                self._header = None
                return response
            else:
                return {
                    "msg_type": "stream",
                    "parent_header": self._header,
                    "content": {"text": result},
                }
        else:
            response = {
                "msg_type": "execute_reply",
                "parent_header": self._header,
                "content": {"status": "ok"},
            }
            self._header = None
            return response


def _url_regex(base_regex: str, route: str) -> Pattern[str]:
    """Construct a regex matching a URL for JupyterHub or its proxy."""
    return re.compile(base_regex + "/" + route)


def _install_hub_routes(
    respx_mock: respx.Router, mock: MockJupyter, base_url: str
) -> None:
    """Install the mock routes for a given JupyterHub base URL.

    Parameters
    ----------
    respx_mock
        Mock router to use to install routes.
    mock
        Jupyter mock providing the routes.
    base_url
        Base URL for the mock routes.
    """
    prefix = base_url.rstrip("/") + "/hub/"
    respx_mock.get(urljoin(prefix, "home")).mock(side_effect=mock.login)
    respx_mock.get(urljoin(prefix, "spawn")).mock(return_value=Response(200))
    respx_mock.post(urljoin(prefix, "spawn")).mock(side_effect=mock.spawn)

    # These routes require regex matching of the username.
    base_regex = re.escape(base_url.rstrip("/") + "/hub")
    regex = _url_regex(base_regex, "spawn-pending/[^/]+$")
    respx_mock.get(url__regex=regex).mock(side_effect=mock.spawn_pending)
    regex = _url_regex(base_regex, "user/[^/]+/lab$")
    respx_mock.get(url__regex=regex).mock(side_effect=mock.missing_lab)
    regex = _url_regex(base_regex, "api/users/[^/]+$")
    respx_mock.get(url__regex=regex).mock(side_effect=mock.user)
    regex = _url_regex(base_regex, "api/users/[^/]+/server/progress$")
    respx_mock.get(url__regex=regex).mock(side_effect=mock.progress)
    regex = _url_regex(base_regex, "api/users/[^/]+/server")
    respx_mock.delete(url__regex=regex).mock(side_effect=mock.delete_lab)


def _install_lab_routes(
    respx_mock: respx.Router, mock: MockJupyter, base_regex: str
) -> None:
    """Install the mock routes for a regular expression of hostnames.

    The lab routes may be hosted at per-user URLs or at a single base URL.

    Parameters
    ----------
    respx_mock
        Mock router to use to install routes.
    mock
        Jupyter mock providing the routes.
    base_regex
        Regular expression matching the base part of the route.
    """
    regex = _url_regex(base_regex, r"user/[^/]+/lab")
    respx_mock.get(url__regex=regex).mock(side_effect=mock.lab)
    regex = _url_regex(base_regex, r"user/[^/]+/oauth_callback")
    respx_mock.get(url__regex=regex).mock(side_effect=mock.lab_callback)
    regex = _url_regex(base_regex, r"user/[^/]+/api/sessions")
    respx_mock.post(url__regex=regex).mock(side_effect=mock.create_session)
    regex = _url_regex(base_regex, r"user/[^/]+/api/sessions/[^/]+$")
    respx_mock.delete(url__regex=regex).mock(side_effect=mock.delete_session)
    regex = _url_regex(base_regex, r"user/[^/]+/rubin/execution")
    respx_mock.post(url__regex=regex).mock(side_effect=mock.run_notebook)


def _mock_jupyter_websocket(
    url: str, headers: dict[str, str], mock_jupyter: MockJupyter
) -> MockJupyterWebSocket:
    """Create a new mock ClientWebSocketResponse that simulates a lab.

    Parameters
    ----------
    url
        URL of the request to open a WebSocket.
    headers
        Extra headers sent with that request.
    mock_jupyter
        Mock JupyterHub and JupyterLab object.

    Returns
    -------
    MockJupyterWebSocket
        Mock WebSocket connection.
    """
    match = re.search("/user/([^/]+)/api/kernels/([^/]+)/channels", url)
    assert match, f"Invalid WebSocket route {url}"
    username = match.group(1)
    session = mock_jupyter.get_session(username)
    assert session, "User has no open lab session"
    kernel_id = match.group(2)
    assert kernel_id == session.kernel_id, (
        f"Kernel doesn't match session: {kernel_id} != {session.kernel_id}"
    )
    return MockJupyterWebSocket(username, session.session_id, mock_jupyter)


@asynccontextmanager
async def register_mock_jupyter(
    respx_mock: respx.Router, *, use_subdomains: bool = False
) -> AsyncGenerator[MockJupyter]:
    """Set up a mock JupyterHub and JupyterLab.

    Parameters
    ----------
    respx_mock
        Mock router to use to install routes.
    use_subdomains
        If set to `True`, use per-user subdomains for JupyterLab and a
        subdomain for JupyterHub. Requests to the URL outside of the subdomain
        will be redirected.
    """
    discovery_client = DiscoveryClient()
    base_url = await discovery_client.url_for_ui("nublado")
    assert base_url, "Service nublado not found in Repertoire"
    mock = MockJupyter(base_url, use_subdomains=use_subdomains)
    _install_hub_routes(respx_mock, mock, base_url)
    _install_lab_routes(respx_mock, mock, re.escape(base_url))
    if use_subdomains:
        parsed_base_url = urlparse(base_url)
        host = parsed_base_url.hostname
        assert host, "Base URL for nublado service has no host component"
        path = parsed_base_url.path.rstrip("/")
        base_regex = r"https://[^.]+\." + re.escape(host) + re.escape(path)
        _install_lab_routes(respx_mock, mock, base_regex)

    @asynccontextmanager
    async def mock_connect(
        url: str,
        additional_headers: dict[str, str],
        max_size: int | None,
        open_timeout: int,
    ) -> AsyncGenerator[MockJupyterWebSocket]:
        yield _mock_jupyter_websocket(url, additional_headers, mock)

    with patch.object(websockets, "connect") as mock_websockets:
        mock_websockets.side_effect = mock_connect
        yield mock
