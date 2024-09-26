"""A mock JupyterHub and lab for tests."""

from __future__ import annotations

import asyncio
import json
import os
import re
from base64 import urlsafe_b64decode
from collections.abc import AsyncIterator
from contextlib import redirect_stdout
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from io import StringIO
from pathlib import Path
from re import Pattern
from traceback import format_exc
from typing import Any
from unittest.mock import ANY
from urllib.parse import parse_qs
from uuid import uuid4

import respx
from httpx import Request, Response
from safir.datetime import current_datetime

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


def _url(environment_url: str, route: str) -> str:
    """Construct a URL for JupyterHub or its proxy."""
    assert environment_url
    base_url = environment_url.rstrip("/")
    return f"{base_url}/nb/{route}"


def _url_regex(environment_url: str, route: str) -> Pattern[str]:
    """Construct a regex matching a URL for JupyterHub or its proxy."""
    assert environment_url
    base_url = environment_url.rstrip("/")
    return re.compile(re.escape(f"{base_url}/nb/") + route)


class MockJupyter:
    """A mock Jupyter state machine.

    This should be invoked via mocked HTTP calls so that tests can simulate
    making REST calls to the real JupyterHub and Lab. It simulates the process
    of spawning a lab, creating a session, and running code within that
    session.

    It also has two result registration methods, ``register_python_result``
    and ``register_extension_result``.  These allow you to mock responses
    for specific Python inputs that would be executed in the running Lab, so
    that you do not need to replicate the target environment in your
    test suite.

    If the username is provided in ``X-Auth-Request-User`` in the request
    headers, that name will be used.  This will be the case when the mock
    is behind something emulating a GafaelfawrIngress, and is how the
    actual Hub would be called.  If it is not, an ``Authorization`` header
    of the form ``Bearer <token>`` will be looked for, and the username
    extracted from the (bogus) token as encoded by
    `~mobu.tests.gafaelfawr.make_gafaelfawr_token`.  This is more accurate
    from the caller perspective.

    The bogus-token functions should be lifted into safir at some point.
    """

    def __init__(
        self,
        base_url: str,
        user_dir: Path,
    ) -> None:
        self.sessions: dict[str, JupyterLabSession] = {}
        self.state: dict[str, JupyterState] = {}
        self.delete_immediate = True
        self.spawn_timeout = False
        self.redirect_loop = False
        self.lab_form: dict[str, dict[str, str]] = {}
        self.expected_session_name = "(no notebook)"
        self.expected_session_type = "console"
        self._delete_at: dict[str, datetime | None] = {}
        self._fail: dict[str, dict[JupyterAction, bool]] = {}
        self._hub_xsrf = os.urandom(8).hex()
        self._lab_xsrf = os.urandom(8).hex()
        self._base_url = base_url
        self._user_dir = user_dir
        self._code_results: dict[str, str] = {}
        self._extension_results: dict[str, NotebookExecutionResult] = {}

    def register_python_result(self, code: str, result: str) -> None:
        """Register the expected cell output for a given source input."""
        self._code_results[code] = result

    def register_extension_result(
        self, code: str, result: NotebookExecutionResult
    ) -> None:
        """Register the expected notebook execution result for a given input
        notebook text.
        """
        cache_key = normalize_source(code)
        self._extension_results[cache_key] = result

    def fail(self, user: str, action: JupyterAction) -> None:
        """Configure the given action to fail for the given user."""
        if user not in self._fail:
            self._fail[user] = {}
        self._fail[user][action] = True

    def _get_user_from_headers(self, request: Request) -> str | None:
        x_user = request.headers.get("X-Auth-Request-User", None)
        if x_user:
            return x_user
        # Try Authorization
        auth = request.headers.get("Authorization", None)
        # Is it a bearer token?
        if auth and auth.startswith("Bearer "):
            tok = auth[len("Bearer ") :]
            # Is it putatively a Gafaelfawr token?
            if tok.startswith("gt-"):
                try:
                    # Try extracting the username
                    return self._extract_user_from_mock_token(token=tok)
                except Exception:
                    pass  # Decoding failed, don't care why.  User is None
        return None

    @staticmethod
    def _extract_user_from_mock_token(token: str) -> str:
        # remove "gt-", and split on the dot that marks the secret
        return urlsafe_b64decode(token[3:].split(".", 1)[0]).decode()

    def login(self, request: Request) -> Response:
        user = self._get_user_from_headers(request)
        if user is None:
            return Response(403, request=request)
        if JupyterAction.LOGIN in self._fail.get(user, {}):
            return Response(500, request=request)
        state = self.state.get(user, JupyterState.LOGGED_OUT)
        if state == JupyterState.LOGGED_OUT:
            self.state[user] = JupyterState.LOGGED_IN
        xsrf = f"_xsrf={self._hub_xsrf}"
        return Response(200, request=request, headers={"Set-Cookie": xsrf})

    def user(self, request: Request) -> Response:
        user = self._get_user_from_headers(request)
        if user is None:
            return Response(403, request=request)
        if JupyterAction.USER in self._fail.get(user, {}):
            return Response(500, request=request)
        assert str(request.url).endswith(f"/hub/api/users/{user}")
        assert request.headers.get("x-xsrftoken") == self._hub_xsrf
        state = self.state.get(user, JupyterState.LOGGED_OUT)
        if state == JupyterState.SPAWN_PENDING:
            server = {"name": "", "pending": "spawn", "ready": False}
            body = {"name": user, "servers": {"": server}}
        elif state == JupyterState.LAB_RUNNING:
            delete_at = self._delete_at.get(user)
            if delete_at and current_datetime(microseconds=True) > delete_at:
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

    async def progress(self, request: Request) -> Response:
        if self.redirect_loop:
            return Response(
                303, headers={"Location": str(request.url)}, request=request
            )
        user = self._get_user_from_headers(request)
        if user is None:
            return Response(403, request=request)
        expected_suffix = f"/hub/api/users/{user}/server/progress"
        assert str(request.url).endswith(expected_suffix)
        assert request.headers.get("x-xsrftoken") == self._hub_xsrf
        state = self.state.get(user, JupyterState.LOGGED_OUT)
        assert state in (JupyterState.SPAWN_PENDING, JupyterState.LAB_RUNNING)
        if JupyterAction.PROGRESS in self._fail.get(user, {}):
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

    def spawn(self, request: Request) -> Response:
        user = self._get_user_from_headers(request)
        if user is None:
            return Response(403, request=request)
        if JupyterAction.SPAWN in self._fail.get(user, {}):
            return Response(500, request=request)
        state = self.state.get(user, JupyterState.LOGGED_OUT)
        assert state == JupyterState.LOGGED_IN
        assert request.headers.get("x-xsrftoken") == self._hub_xsrf
        self.state[user] = JupyterState.SPAWN_PENDING
        self.lab_form[user] = {
            k: v[0] for k, v in parse_qs(request.content.decode()).items()
        }
        url = _url(self._base_url, f"hub/spawn-pending/{user}")
        return Response(302, headers={"Location": url}, request=request)

    def spawn_pending(self, request: Request) -> Response:
        user = self._get_user_from_headers(request)
        if user is None:
            return Response(403, request=request)
        assert str(request.url).endswith(f"/hub/spawn-pending/{user}")
        if JupyterAction.SPAWN_PENDING in self._fail.get(user, {}):
            return Response(500, request=request)
        state = self.state.get(user, JupyterState.LOGGED_OUT)
        assert state == JupyterState.SPAWN_PENDING
        assert request.headers.get("x-xsrftoken") == self._hub_xsrf
        return Response(200, request=request)

    def missing_lab(self, request: Request) -> Response:
        user = self._get_user_from_headers(request)
        if user is None:
            return Response(403, request=request)
        assert str(request.url).endswith(f"/hub/user/{user}/lab")
        return Response(503, request=request)

    def lab(self, request: Request) -> Response:
        user = self._get_user_from_headers(request)
        if user is None:
            return Response(403, request=request)
        assert str(request.url).endswith(f"/user/{user}/lab")
        if JupyterAction.LAB in self._fail.get(user, {}):
            return Response(500, request=request)
        state = self.state.get(user, JupyterState.LOGGED_OUT)
        if state == JupyterState.LAB_RUNNING:
            # In real life, there's another redirect to
            # /hub/api/oauth2/authorize, which doesn't set a cookie,
            # and then redirects to /user/username/oauth_callback.
            #
            # We're skipping that one since it doesn't change the
            # client state at all.
            xsrf = f"_xsrf={self._lab_xsrf}"
            return Response(
                302,
                request=request,
                headers={
                    "Location": _url(
                        self._base_url, f"user/{user}/oauth_callback"
                    ),
                    "Set-Cookie": xsrf,
                },
            )
        else:
            return Response(
                302,
                headers={
                    "Location": _url(self._base_url, f"hub/user/{user}/lab")
                },
                request=request,
            )

    def lab_callback(self, request: Request) -> Response:
        """Simulate not setting the ``_xsrf`` cookie on first request.

        This happens at the end of a chain from ``/user/username/lab`` to
        ``/hub/api/oauth2/authorize``, which then issues a redirect to
        ``/user/username/oauth_callback``.  It is in the final redirect
        that the ``_xsrf`` cookie is actually set, and then it returns
        a 200.
        """
        user = self._get_user_from_headers(request)
        if user is None:
            return Response(403, request=request)
        assert str(request.url).endswith(f"/user/{user}/oauth_callback")
        return Response(200, request=request)

    def delete_lab(self, request: Request) -> Response:
        user = self._get_user_from_headers(request)
        if user is None:
            return Response(403, request=request)
        assert str(request.url).endswith(f"/users/{user}/server")
        assert request.headers.get("x-xsrftoken") == self._hub_xsrf
        if JupyterAction.DELETE_LAB in self._fail.get(user, {}):
            return Response(500, request=request)
        state = self.state.get(user, JupyterState.LOGGED_OUT)
        assert state != JupyterState.LOGGED_OUT
        if self.delete_immediate:
            self.state[user] = JupyterState.LOGGED_IN
        else:
            now = current_datetime(microseconds=True)
            self._delete_at[user] = now + timedelta(seconds=5)
        return Response(202, request=request)

    def create_session(self, request: Request) -> Response:
        user = self._get_user_from_headers(request)
        if user is None:
            return Response(403, request=request)
        assert str(request.url).endswith(f"/user/{user}/api/sessions")
        assert request.headers.get("x-xsrftoken") == self._lab_xsrf
        assert user not in self.sessions
        if JupyterAction.CREATE_SESSION in self._fail.get(user, {}):
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

    def delete_session(self, request: Request) -> Response:
        user = self._get_user_from_headers(request)
        if user is None:
            return Response(403, request=request)
        session_id = self.sessions[user].session_id
        expected_suffix = f"/user/{user}/api/sessions/{session_id}"
        assert str(request.url).endswith(expected_suffix)
        assert request.headers.get("x-xsrftoken") == self._lab_xsrf
        if JupyterAction.DELETE_SESSION in self._fail.get(user, {}):
            return Response(500, request=request)
        state = self.state.get(user, JupyterState.LOGGED_OUT)
        assert state == JupyterState.LAB_RUNNING
        del self.sessions[user]
        return Response(204, request=request)

    def get_content(self, request: Request) -> Response:
        """Simulate the /files retrieval endpoint."""
        user = self._get_user_from_headers(request)
        if user is None:
            return Response(403, request=request)
        state = self.state.get(user, JupyterState.LOGGED_OUT)
        assert state == JupyterState.LAB_RUNNING
        contents_url = _url(self._base_url, f"user/{user}/files/")
        assert str(request.url).startswith(contents_url)
        path = str(request.url)[len(contents_url) :]
        try:
            filename = self._user_dir / path
            content = filename.read_bytes()
            return Response(200, content=content, request=request)
        except FileNotFoundError:
            return Response(
                404,
                content=f"file or directory '{path}' does not exist".encode(),
            )

    def run_notebook_via_extension(self, request: Request) -> Response:
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
        self._parent: MockJupyter = parent
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
        if self._code in self._parent._code_results:
            code = self._code
            self._code = None
            return {
                "msg_type": "stream",
                "parent_header": self._header,
                "content": {"text": self._parent._code_results[code]},
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


def mock_jupyter(
    respx_mock: respx.Router,
    base_url: str,
    user_dir: Path,
) -> MockJupyter:
    """Set up a mock JupyterHub and lab."""
    mock = MockJupyter(base_url=base_url, user_dir=user_dir)
    respx_mock.get(_url(base_url, "hub/home")).mock(side_effect=mock.login)
    respx_mock.get(_url(base_url, "hub/spawn")).mock(
        return_value=Response(200)
    )
    respx_mock.post(_url(base_url, "hub/spawn")).mock(side_effect=mock.spawn)
    regex = _url_regex(base_url, "hub/spawn-pending/[^/]+$")
    respx_mock.get(url__regex=regex).mock(side_effect=mock.spawn_pending)
    regex = _url_regex(base_url, "hub/user/[^/]+/lab$")
    respx_mock.get(url__regex=regex).mock(side_effect=mock.missing_lab)
    regex = _url_regex(base_url, "hub/api/users/[^/]+$")
    respx_mock.get(url__regex=regex).mock(side_effect=mock.user)
    regex = _url_regex(base_url, "hub/api/users/[^/]+/server/progress$")
    respx_mock.get(url__regex=regex).mock(side_effect=mock.progress)
    regex = _url_regex(base_url, "hub/api/users/[^/]+/server")
    respx_mock.delete(url__regex=regex).mock(side_effect=mock.delete_lab)
    regex = _url_regex(base_url, r"user/[^/]+/lab")
    respx_mock.get(url__regex=regex).mock(side_effect=mock.lab)
    regex = _url_regex(base_url, r"user/[^/]+/oauth_callback")
    respx_mock.get(url__regex=regex).mock(side_effect=mock.lab_callback)
    regex = _url_regex(base_url, "user/[^/]+/api/sessions")
    respx_mock.post(url__regex=regex).mock(side_effect=mock.create_session)
    regex = _url_regex(base_url, "user/[^/]+/api/sessions/[^/]+$")
    respx_mock.delete(url__regex=regex).mock(side_effect=mock.delete_session)
    regex = _url_regex(base_url, "user/[^/]+/files/[^/]+$")
    respx_mock.get(url__regex=regex).mock(side_effect=mock.get_content)
    regex = _url_regex(base_url, "user/[^/]+/rubin/execution")
    respx_mock.post(url__regex=regex).mock(
        side_effect=mock.run_notebook_via_extension
    )
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
