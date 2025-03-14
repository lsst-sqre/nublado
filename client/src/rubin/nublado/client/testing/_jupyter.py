"""A mock JupyterHub and lab for tests."""

from __future__ import annotations

import asyncio
import json
import os
import re
from base64 import urlsafe_b64decode
from collections import defaultdict
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import redirect_stdout
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from functools import wraps
from io import StringIO
from pathlib import Path
from re import Pattern
from traceback import format_exc
from typing import Any
from unittest.mock import ANY
from urllib.parse import parse_qs, urljoin, urlparse
from uuid import uuid4

import respx
from httpx import URL, Request, Response

from .._util import normalize_source
from ..models import NotebookExecutionResult


class JupyterAction(Enum):
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
class JupyterLabSession:
    """Metadata for an open Jupyter lab session."""

    session_id: str
    kernel_id: str


class JupyterState(Enum):
    """Possible states the Jupyter lab can be in."""

    LOGGED_OUT = "logged out"
    LOGGED_IN = "logged in"
    SPAWN_PENDING = "spawn pending"
    LAB_RUNNING = "lab running"


type MockSideEffect = Callable[
    [MockJupyter, Request], Coroutine[None, None, Response]
]
"""Type of a respx mock side effect function."""

type MockHandler = Callable[
    [MockJupyter, Request, str], Coroutine[None, None, Response]
]
"""Type of a handler for a mocked Jupyter call."""


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
    user_dir
        Simulated user home directory for the ``/files`` route.
    use_subdomains
        If `True`, simulate per-user subdomains. JupyterHub will use the URL
        :samp:`nb.{hostname}` where the hostname is taken from ``base_url``,
        and JupyterLab will use :samp:`{username}.nb.{hostname}`.
    """

    def __init__(
        self,
        base_url: str,
        user_dir: Path,
        *,
        use_subdomains: bool = False,
    ) -> None:
        self._base_url = URL(base_url)
        self._user_dir = user_dir
        self._use_subdomains = use_subdomains

        self.sessions: dict[str, JupyterLabSession] = {}
        self.state: dict[str, JupyterState] = {}
        self.delete_immediate = True
        self.spawn_timeout = False
        self.redirect_loop = False
        self.lab_form: dict[str, dict[str, str]] = {}
        self.expected_session_name = "(no notebook)"
        self.expected_session_type = "console"

        self._delete_at: dict[str, datetime | None] = {}
        self._fail: defaultdict[str, set[JupyterAction]] = defaultdict(set)
        self._hub_xsrf = os.urandom(8).hex()
        self._lab_xsrf = os.urandom(8).hex()
        self._code_results: dict[str, str] = {}
        self._extension_results: dict[str, NotebookExecutionResult] = {}

    def fail(self, user: str, action: JupyterAction) -> None:
        """Configure the given action to fail for the given user."""
        self._fail[user].add(action)

    def get_python_result(self, code: str | None) -> str | None:
        """Get the cached results for a specific block of code.

        Parameters
        ----------
        code
            Code for which to retrieve results.

        Returns
        -------
        str or None
            Corresponding results, or `None` if there are no results for this
            code.
        """
        if not code:
            return None
        return self._code_results.get(code)

    def register_extension_result(
        self, code: str, result: NotebookExecutionResult
    ) -> None:
        """Register the expected notebook execution result for a given input
        notebook text.
        """
        cache_key = normalize_source(code)
        self._extension_results[cache_key] = result

    def register_python_result(self, code: str, result: str) -> None:
        """Register the expected cell output for a given source input."""
        self._code_results[code] = result

    # Below this point are the mock handler methods for the various routes.
    # None of these methods should normally be called directly by test code.
    # They are registered with respx and invoked automatically when a request
    # is sent by the code under test to the mocked JupyterHub or JupyterLab.

    @staticmethod
    def _check(
        *, url_format: str | None = None
    ) -> Callable[[MockHandler], MockSideEffect]:
        """Wrap `MockJupyter` methods to perform common checks.

        There are various common checks that should be performed for every
        request to the mock, and the username always has to be extracted from
        the token and injected as an additional argument to the method. This
        wrapper performs those checks and then injects the username of the
        authenticated user into the underlying handler.

        Paramaters
        ----------
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

        def decorator(f: MockHandler) -> MockSideEffect:
            @wraps(f)
            async def wrapper(mock: MockJupyter, request: Request) -> Response:
                # Ensure the request is authenticated.
                user = mock._get_user_from_headers(request)
                if user is None:
                    return Response(403, request=request)

                # If told to check the URL, verify it has the right path.
                if url_format:
                    expected = url_format.format(user=user)
                    request_url = str(request.url)
                    if expected not in request_url:
                        msg = f"URL {request_url} does not contain {expected}"
                        raise RuntimeError(msg)

                # Handle any redirects needed by the multi-domain case.
                if redirect := mock._maybe_redirect(request, user):
                    return Response(
                        302, request=request, headers={"Location": redirect}
                    )

                # All checks passed. Call the actual handler.
                return await f(mock, request, user)

            return wrapper

        return decorator

    @_check()
    async def login(self, request: Request, user: str) -> Response:
        if JupyterAction.LOGIN in self._fail[user]:
            return Response(500, request=request)
        state = self.state.get(user, JupyterState.LOGGED_OUT)
        if state == JupyterState.LOGGED_OUT:
            self.state[user] = JupyterState.LOGGED_IN
        xsrf = f"_xsrf={self._hub_xsrf}"
        return Response(200, request=request, headers={"Set-Cookie": xsrf})

    @_check(url_format="/hub/api/users/{user}")
    async def user(self, request: Request, user: str) -> Response:
        if JupyterAction.USER in self._fail[user]:
            return Response(500, request=request)
        assert request.headers.get("x-xsrftoken") == self._hub_xsrf
        state = self.state.get(user, JupyterState.LOGGED_OUT)
        if state == JupyterState.SPAWN_PENDING:
            server = {"name": "", "pending": "spawn", "ready": False}
            body = {"name": user, "servers": {"": server}}
        elif state == JupyterState.LAB_RUNNING:
            delete_at = self._delete_at.get(user)
            if delete_at and datetime.now(tz=UTC) > delete_at:
                del self._delete_at[user]
                self.state[user] = JupyterState.LOGGED_IN
            if delete_at:
                server = {"name": "", "pending": "delete", "ready": False}
            else:
                server = {"name": "", "pending": None, "ready": True}
            body = {"name": user, "servers": {"": server}}
        else:
            body = {"name": user, "servers": {}}
        return Response(200, json=body, request=request)

    @_check(url_format="/hub/api/users/{user}/server/progress")
    async def progress(self, request: Request, user: str) -> Response:
        if self.redirect_loop:
            return Response(
                303, headers={"Location": str(request.url)}, request=request
            )
        state = self.state.get(user, JupyterState.LOGGED_OUT)
        assert state in (JupyterState.SPAWN_PENDING, JupyterState.LAB_RUNNING)
        if JupyterAction.PROGRESS in self._fail[user]:
            body = (
                'data: {"progress": 0, "message": "Server requested"}\n\n'
                'data: {"progress": 50, "message": "Spawning server..."}\n\n'
                'data: {"progress": 75, "message": "Spawn failed!"}\n\n'
            )
        elif state == JupyterState.LAB_RUNNING:
            body = (
                'data: {"progress": 100, "ready": true, "message": "Ready"}\n'
                "\n"
            )
        elif self.spawn_timeout:
            # Cause the spawn to time out by pausing for longer than the test
            # should run for and then returning nothing.
            await asyncio.sleep(60)
            body = ""
        else:
            self.state[user] = JupyterState.LAB_RUNNING
            body = (
                'data: {"progress": 0, "message": "Server requested"}\n\n'
                'data: {"progress": 50, "message": "Spawning server..."}\n\n'
                'data: {"progress": 100, "ready": true, "message": "Ready"}\n'
                "\n"
            )
        return Response(
            200,
            text=body,
            headers={"Content-Type": "text/event-stream"},
            request=request,
        )

    @_check()
    async def spawn(self, request: Request, user: str) -> Response:
        if JupyterAction.SPAWN in self._fail[user]:
            return Response(500, request=request)
        state = self.state.get(user, JupyterState.LOGGED_OUT)
        assert state == JupyterState.LOGGED_IN
        assert request.headers.get("x-xsrftoken") == self._hub_xsrf
        self.state[user] = JupyterState.SPAWN_PENDING
        self.lab_form[user] = {
            k: v[0] for k, v in parse_qs(request.content.decode()).items()
        }
        url = self._url(f"hub/spawn-pending/{user}")
        return Response(302, headers={"Location": url}, request=request)

    @_check(url_format="/hub/spawn-pending/{user}")
    async def spawn_pending(self, request: Request, user: str) -> Response:
        if JupyterAction.SPAWN_PENDING in self._fail[user]:
            return Response(500, request=request)
        state = self.state.get(user, JupyterState.LOGGED_OUT)
        assert state == JupyterState.SPAWN_PENDING
        assert request.headers.get("x-xsrftoken") == self._hub_xsrf
        return Response(200, request=request)

    @_check(url_format="/hub/user/{user}/lab")
    async def missing_lab(self, request: Request, user: str) -> Response:
        return Response(503, request=request)

    @_check(url_format="/user/{user}/lab")
    async def lab(self, request: Request, user: str) -> Response:
        if JupyterAction.LAB in self._fail[user]:
            return Response(500, request=request)
        state = self.state.get(user, JupyterState.LOGGED_OUT)
        if state == JupyterState.LAB_RUNNING:
            # In real life, there's another redirect to
            # /hub/api/oauth2/authorize, which doesn't set a cookie, and then
            # redirects to /user/username/oauth_callback. We're skipping that
            # one since it doesn't change the client state at all.
            xsrf = f"_xsrf={self._lab_xsrf}"
            return Response(
                302,
                request=request,
                headers={
                    "Location": self._url(f"user/{user}/oauth_callback"),
                    "Set-Cookie": xsrf,
                },
            )
        else:
            if self._use_subdomains:
                host = "nb." + self._base_url.host
            else:
                host = self._base_url.host
            return Response(
                302,
                headers={"Location": self._url(f"hub/user/{user}/lab", host)},
                request=request,
            )

    @_check(url_format="/user/{user}/oauth_callback")
    async def lab_callback(self, request: Request, user: str) -> Response:
        """Simulate not setting the ``_xsrf`` cookie on first request.

        This happens at the end of a chain from ``/user/username/lab`` to
        ``/hub/api/oauth2/authorize``, which then issues a redirect to
        ``/user/username/oauth_callback``. It is in the final redirect that
        the ``_xsrf`` cookie is actually set, and then this callback returns a
        200 response without setting a cookie.
        """
        return Response(200, request=request)

    @_check(url_format="/hub/api/users/{user}/server")
    async def delete_lab(self, request: Request, user: str) -> Response:
        assert request.headers.get("x-xsrftoken") == self._hub_xsrf
        if JupyterAction.DELETE_LAB in self._fail[user]:
            return Response(500, request=request)
        state = self.state.get(user, JupyterState.LOGGED_OUT)
        assert state != JupyterState.LOGGED_OUT
        if self.delete_immediate:
            self.state[user] = JupyterState.LOGGED_IN
        else:
            now = datetime.now(tz=UTC)
            self._delete_at[user] = now + timedelta(seconds=5)
        return Response(202, request=request)

    @_check(url_format="/user/{user}/api/sessions")
    async def create_session(self, request: Request, user: str) -> Response:
        assert request.headers.get("x-xsrftoken") == self._lab_xsrf
        assert user not in self.sessions
        if JupyterAction.CREATE_SESSION in self._fail[user]:
            return Response(500, request=request)
        state = self.state.get(user, JupyterState.LOGGED_OUT)
        assert state == JupyterState.LAB_RUNNING
        body = json.loads(request.content.decode())
        assert body["kernel"]["name"] == "LSST"
        assert body["name"] == self.expected_session_name
        assert body["type"] == self.expected_session_type
        session = JupyterLabSession(
            session_id=uuid4().hex, kernel_id=uuid4().hex
        )
        self.sessions[user] = session
        return Response(
            201,
            json={
                "id": session.session_id,
                "kernel": {"id": session.kernel_id},
            },
            request=request,
        )

    @_check(url_format="/user/{user}/api/sessions")
    async def delete_session(self, request: Request, user: str) -> Response:
        session_id = self.sessions[user].session_id
        assert str(request.url).endswith(f"/{session_id}")
        assert request.headers.get("x-xsrftoken") == self._lab_xsrf
        if JupyterAction.DELETE_SESSION in self._fail[user]:
            return Response(500, request=request)
        state = self.state.get(user, JupyterState.LOGGED_OUT)
        assert state == JupyterState.LAB_RUNNING
        del self.sessions[user]
        return Response(204, request=request)

    @_check(url_format="/user/{user}/files")
    async def get_content(self, request: Request, user: str) -> Response:
        """Simulate the /files retrieval endpoint."""
        state = self.state.get(user, JupyterState.LOGGED_OUT)
        assert state == JupyterState.LAB_RUNNING
        if self._use_subdomains:
            host = f"{user}.nb." + self._base_url.host
        else:
            host = self._base_url.host
        contents_url = self._url(f"user/{user}/files/", host)
        assert str(request.url).startswith(contents_url)
        path = str(request.url)[len(contents_url) :]
        try:
            filename = self._user_dir / path
            content = filename.read_bytes()
            return Response(200, content=content, request=request)
        except FileNotFoundError:
            return Response(
                404, text=f"file or directory '{path}' does not exist"
            )

    @_check()
    async def run_notebook_via_extension(
        self, request: Request, user: str
    ) -> Response:
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
        inp = request.content.decode("utf-8")
        try:
            obj = json.loads(inp)
            nb_str = json.dumps(obj["notebook"])
            resources = obj["resources"]
        except Exception:
            nb_str = inp
            resources = None
        normalized_nb_code = normalize_source(nb_str)
        if normalized_nb_code in self._extension_results:
            res = self._extension_results[normalized_nb_code]
            obj = res.model_dump()
        else:
            obj = {
                "notebook": nb_str,
                "resources": resources or {},
                "error": None,
            }
        return Response(200, json=obj)

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
        if username := request.headers.get("X-Auth-Request-User", None):
            return username
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
        if f"user/{user}" in request.url.path:
            # Simulate two redirects, one to the JupyterHub hostname and then
            # a second to the JupyterLab hostname, since that appears to be
            # what JupyterHub actually does.
            if host.startswith("nb."):
                return str(request.url.copy_with(host=f"{user}.{host}"))
            elif not host.startswith(f"{user}.nb."):
                return str(request.url.copy_with(host=f"nb.{host}"))
            else:
                return None
        elif "hub/" in request.url.path:
            if host.startswith("nb."):
                return None
            else:
                return str(request.url.copy_with(host=f"nb.{host}"))
        else:
            raise RuntimeError(f"Unknown URL {request.url}")

    def _url(self, route: str, host: str | None = None) -> str:
        """Construct a URL for a redirect.

        Parameters
        ----------
        route
            Path portion of the redirect.
        host
            Host portion of the redirect, if one should be present.
        """
        path = self._base_url.path.rstrip("/") + f"/nb/{route}"
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
    The methods are named the reverse of what you would expect:  ``send``
    receives a message, and ``recv`` sends a message back to the caller. This
    is because this is a mock of a client library but is simulating a server,
    so is operating in the reverse direction.
    """

    def __init__(
        self, user: str, session_id: str, parent: MockJupyter
    ) -> None:
        self.user = user
        self.session_id = session_id
        self._header: dict[str, str] | None = None
        self._code: str | None = None
        self._parent = parent
        self._state: dict[str, Any] = {}

    async def close(self) -> None:
        pass

    async def send(self, message_str: str) -> None:
        message = json.loads(message_str)
        assert message == {
            "header": {
                "username": self.user,
                "version": "5.4",
                "session": self.session_id,
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
        self._header = message["header"]
        self._code = message["content"]["code"]

    async def __aiter__(self) -> AsyncIterator[str]:
        while True:
            assert self._header
            response = self._build_response()
            yield json.dumps(response)

    def _build_response(self) -> dict[str, Any]:
        if results := self._parent.get_python_result(self._code):
            self._code = None
            return {
                "msg_type": "stream",
                "parent_header": self._header,
                "content": {"text": results},
            }
        elif self._code == "long_error_for_test()":
            error = ""
            line = "this is a single line of output to test trimming errors"
            for i in range(int(3000 / len(line))):
                error += f"{line} #{i}\n"
            self._code = None
            return {
                "msg_type": "error",
                "parent_header": self._header,
                "content": {"traceback": error},
            }
        elif self._code:
            try:
                output = StringIO()
                with redirect_stdout(output):
                    exec(self._code, self._state)  # noqa: S102
                self._code = None
                return {
                    "msg_type": "stream",
                    "parent_header": self._header,
                    "content": {"text": output.getvalue()},
                }
            except Exception:
                result = {
                    "msg_type": "error",
                    "parent_header": self._header,
                    "content": {"traceback": format_exc()},
                }
                self._header = None
                return result
        else:
            result = {
                "msg_type": "execute_reply",
                "parent_header": self._header,
                "content": {"status": "ok"},
            }
            self._header = None
            return result


def _url_regex(host_regex: str, route: str) -> Pattern[str]:
    """Construct a regex matching a URL for JupyterHub or its proxy."""
    return re.compile(f"https://{host_regex}/{route}")


def _install_hub_routes(
    respx_mock: respx.Router, mock: MockJupyter, host: str
) -> None:
    """Install the mock routes for a given JupyterHub base URL.

    Parameters
    ----------
    respx_mock
        Mock router to use to install routes.
    mock
        Jupyter mock providing the routes.
    host
        Hostname under which to install the mock routes.
    """
    base_url = f"https://{host}/nb/hub/"
    respx_mock.get(urljoin(base_url, "home")).mock(side_effect=mock.login)
    respx_mock.get(urljoin(base_url, "spawn")).mock(return_value=Response(200))
    respx_mock.post(urljoin(base_url, "spawn")).mock(side_effect=mock.spawn)

    # These routes require regex matching of the username.
    host_regex = re.escape(host)
    regex = _url_regex(host_regex, "nb/hub/spawn-pending/[^/]+$")
    respx_mock.get(url__regex=regex).mock(side_effect=mock.spawn_pending)
    regex = _url_regex(host_regex, "nb/hub/user/[^/]+/lab$")
    respx_mock.get(url__regex=regex).mock(side_effect=mock.missing_lab)
    regex = _url_regex(host_regex, "nb/hub/api/users/[^/]+$")
    respx_mock.get(url__regex=regex).mock(side_effect=mock.user)
    regex = _url_regex(host_regex, "nb/hub/api/users/[^/]+/server/progress$")
    respx_mock.get(url__regex=regex).mock(side_effect=mock.progress)
    regex = _url_regex(host_regex, "nb/hub/api/users/[^/]+/server")
    respx_mock.delete(url__regex=regex).mock(side_effect=mock.delete_lab)


def _install_lab_routes(
    respx_mock: respx.Router, mock: MockJupyter, host_regex: str
) -> None:
    """Install the mock routes for a regular expression of hostnames.

    The lab routes may be hosted at per-user URLs or at a single base URL.

    Parameters
    ----------
    respx_mock
        Mock router to use to install routes.
    mock
        Jupyter mock providing the routes.
    host_regex
        Regular expression matching the hostname of the route.
    """
    regex = _url_regex(host_regex, r"nb/user/[^/]+/lab")
    respx_mock.get(url__regex=regex).mock(side_effect=mock.lab)
    regex = _url_regex(host_regex, r"nb/user/[^/]+/oauth_callback")
    respx_mock.get(url__regex=regex).mock(side_effect=mock.lab_callback)
    regex = _url_regex(host_regex, r"nb/user/[^/]+/api/sessions")
    respx_mock.post(url__regex=regex).mock(side_effect=mock.create_session)
    regex = _url_regex(host_regex, r"nb/user/[^/]+/api/sessions/[^/]+$")
    respx_mock.delete(url__regex=regex).mock(side_effect=mock.delete_session)
    regex = _url_regex(host_regex, "nb/user/[^/]+/files/[^/]+$")
    respx_mock.get(url__regex=regex).mock(side_effect=mock.get_content)
    regex = _url_regex(host_regex, "nb/user/[^/]+/rubin/execution")
    respx_mock.post(url__regex=regex).mock(
        side_effect=mock.run_notebook_via_extension
    )


def mock_jupyter(
    respx_mock: respx.Router,
    base_url: str,
    user_dir: Path,
    *,
    use_subdomains: bool = False,
) -> MockJupyter:
    """Set up a mock JupyterHub and JupyterLab.

    Parameters
    ----------
    respx_mock
        Mock router to use to install routes.
    base_url
        Base URL for JupyterHub. Only the hostname will be used and ``/nb``
        will always be appended. If per-user subdomains are in use, this is
        the base URL without subdomains and the subdomain URLs will be created
        by prepending ``nb.`` or :samp:`{username}.nb.` to the hostname of
        this URL.
    user_dir
        User directory for mocking ``/files`` responses.
    use_subdomains
        If set to `True`, use per-user subdomains for JupyterLab and a
        subdomain for JupyterHub. Requests to the URL outside of the subdomain
        will be redirected.
    """
    mock = MockJupyter(base_url, user_dir, use_subdomains=use_subdomains)
    host = urlparse(base_url).hostname
    assert host
    _install_hub_routes(respx_mock, mock, host)
    _install_lab_routes(respx_mock, mock, re.escape(host))
    if use_subdomains:
        _install_hub_routes(respx_mock, mock, f"nb.{host}")
        _install_lab_routes(respx_mock, mock, re.escape(f"nb.{host}"))
        per_user_host_regex = r"[^.]+\.nb\." + re.escape(host)
        _install_lab_routes(respx_mock, mock, per_user_host_regex)
    return mock


def mock_jupyter_websocket(
    url: str, headers: dict[str, str], jupyter: MockJupyter
) -> MockJupyterWebSocket:
    """Create a new mock ClientWebSocketResponse that simulates a lab.

    Parameters
    ----------
    url
        URL of the request to open a WebSocket.
    headers
        Extra headers sent with that request.
    jupyter
        Mock JupyterHub.

    Returns
    -------
    MockJupyterWebSocket
        Mock WebSocket connection.
    """
    match = re.search("/user/([^/]+)/api/kernels/([^/]+)/channels", url)
    assert match
    user = match.group(1)
    session = jupyter.sessions[user]
    assert match.group(2) == session.kernel_id
    return MockJupyterWebSocket(user, session.session_id, parent=jupyter)
