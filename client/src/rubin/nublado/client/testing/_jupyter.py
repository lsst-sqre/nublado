"""A mock JupyterHub and lab for tests."""

from __future__ import annotations

import asyncio
import json
import os
import re
from base64 import urlsafe_b64decode
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import redirect_stdout, suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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
        self._fail[user].add(action)

    def login(self, request: Request) -> Response:
        user = self._get_user_from_headers(request)
        if user is None:
            return Response(403, request=request)
        if redirect := self._maybe_redirect(request, user):
            return Response(
                302, request=request, headers={"Location": redirect}
            )
        if JupyterAction.LOGIN in self._fail[user]:
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
        if redirect := self._maybe_redirect(request, user):
            return Response(
                302, request=request, headers={"Location": redirect}
            )
        if JupyterAction.USER in self._fail[user]:
            return Response(500, request=request)
        assert str(request.url).endswith(f"/hub/api/users/{user}")
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

    async def progress(self, request: Request) -> Response:
        if self.redirect_loop:
            return Response(
                303, headers={"Location": str(request.url)}, request=request
            )
        user = self._get_user_from_headers(request)
        if user is None:
            return Response(403, request=request)
        if redirect := self._maybe_redirect(request, user):
            return Response(
                302, request=request, headers={"Location": redirect}
            )
        expected_suffix = f"/hub/api/users/{user}/server/progress"
        assert str(request.url).endswith(expected_suffix)
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

    def spawn(self, request: Request) -> Response:
        user = self._get_user_from_headers(request)
        if user is None:
            return Response(403, request=request)
        if redirect := self._maybe_redirect(request, user):
            return Response(
                302, request=request, headers={"Location": redirect}
            )
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

    def spawn_pending(self, request: Request) -> Response:
        user = self._get_user_from_headers(request)
        if user is None:
            return Response(403, request=request)
        if redirect := self._maybe_redirect(request, user):
            return Response(
                302, request=request, headers={"Location": redirect}
            )
        assert str(request.url).endswith(f"/hub/spawn-pending/{user}")
        if JupyterAction.SPAWN_PENDING in self._fail[user]:
            return Response(500, request=request)
        state = self.state.get(user, JupyterState.LOGGED_OUT)
        assert state == JupyterState.SPAWN_PENDING
        assert request.headers.get("x-xsrftoken") == self._hub_xsrf
        return Response(200, request=request)

    def missing_lab(self, request: Request) -> Response:
        user = self._get_user_from_headers(request)
        if user is None:
            return Response(403, request=request)
        if redirect := self._maybe_redirect(request, user):
            return Response(
                302, request=request, headers={"Location": redirect}
            )
        assert str(request.url).endswith(f"/hub/user/{user}/lab")
        return Response(503, request=request)

    def lab(self, request: Request) -> Response:
        user = self._get_user_from_headers(request)
        if user is None:
            return Response(403, request=request)
        if redirect := self._maybe_redirect(request, user):
            return Response(
                302, request=request, headers={"Location": redirect}
            )
        assert str(request.url).endswith(f"/user/{user}/lab")
        if JupyterAction.LAB in self._fail[user]:
            return Response(500, request=request)
        state = self.state.get(user, JupyterState.LOGGED_OUT)
        if state == JupyterState.LAB_RUNNING:
            # In real life, there's another redirect to
            # /hub/api/oauth2/authorize, which doesn't set a cookie, and then
            # redirects to /user/username/oauth_callback.
            #
            # We're skipping that one since it doesn't change the client state
            # at all.
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
        if redirect := self._maybe_redirect(request, user):
            return Response(
                302, request=request, headers={"Location": redirect}
            )
        assert str(request.url).endswith(f"/user/{user}/oauth_callback")
        return Response(200, request=request)

    def delete_lab(self, request: Request) -> Response:
        user = self._get_user_from_headers(request)
        if user is None:
            return Response(403, request=request)
        if redirect := self._maybe_redirect(request, user):
            return Response(
                302, request=request, headers={"Location": redirect}
            )
        assert str(request.url).endswith(f"/hub/api/users/{user}/server")
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

    def create_session(self, request: Request) -> Response:
        user = self._get_user_from_headers(request)
        if user is None:
            return Response(403, request=request)
        if redirect := self._maybe_redirect(request, user):
            return Response(
                302, request=request, headers={"Location": redirect}
            )
        assert str(request.url).endswith(f"/user/{user}/api/sessions")
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

    def delete_session(self, request: Request) -> Response:
        user = self._get_user_from_headers(request)
        if user is None:
            return Response(403, request=request)
        if redirect := self._maybe_redirect(request, user):
            return Response(
                302, request=request, headers={"Location": redirect}
            )
        session_id = self.sessions[user].session_id
        expected_suffix = f"/user/{user}/api/sessions/{session_id}"
        assert str(request.url).endswith(expected_suffix)
        assert request.headers.get("x-xsrftoken") == self._lab_xsrf
        if JupyterAction.DELETE_SESSION in self._fail[user]:
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
        if redirect := self._maybe_redirect(request, user):
            return Response(
                302, request=request, headers={"Location": redirect}
            )
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

    @staticmethod
    def _extract_user_from_mock_token(token: str) -> str:
        # remove "gt-", and split on the dot that marks the secret
        return urlsafe_b64decode(token[3:].split(".", 1)[0]).decode()

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
                with suppress(Exception):
                    # Try extracting the username. If this fails, fall through
                    # and return None.
                    return self._extract_user_from_mock_token(token=tok)
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
        Base URL into which to install routes.
    """
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


def _install_lab_routes(
    respx_mock: respx.Router, mock: MockJupyter, base_regex: str
) -> None:
    """Install the mock routes for a given JupyterLab base URL.

    Parameters
    ----------
    respx_mock
        Mock router to use to install routes.
    mock
        Jupyter mock providing the routes.
    base_regex
        Regex of base URL into which to install routes.
    """
    regex = base_regex + r"/user/[^/]+/lab"
    respx_mock.get(url__regex=regex).mock(side_effect=mock.lab)
    regex = base_regex + r"/user/[^/]+/oauth_callback"
    respx_mock.get(url__regex=regex).mock(side_effect=mock.lab_callback)
    regex = base_regex + r"/user/[^/]+/api/sessions"
    respx_mock.post(url__regex=regex).mock(side_effect=mock.create_session)
    regex = base_regex + r"/user/[^/]+/api/sessions/[^/]+$"
    respx_mock.delete(url__regex=regex).mock(side_effect=mock.delete_session)
    regex = base_regex + "/user/[^/]+/files/[^/]+$"
    respx_mock.get(url__regex=regex).mock(side_effect=mock.get_content)
    regex = base_regex + "/user/[^/]+/rubin/execution"
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
        Base URL for JupyterHub. If per-user subdomains are in use, this is
        the base URL without subdomains. The subdomain URLs will be created
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
    _install_hub_routes(respx_mock, mock, base_url)
    _install_lab_routes(respx_mock, mock, base_url + "/nb")
    if use_subdomains:
        parsed_url = URL(base_url)
        hub_url = parsed_url.copy_with(host=f"nb.{parsed_url.host}")
        _install_hub_routes(respx_mock, mock, str(hub_url))
        _install_lab_routes(respx_mock, mock, str(hub_url) + "/nb")
        path = parsed_url.path.rstrip("/") + "/nb"
        lab_regex = rf"https://[^.]+\.nb\.{parsed_url.host}{path}"
        _install_lab_routes(respx_mock, mock, lab_regex)
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
