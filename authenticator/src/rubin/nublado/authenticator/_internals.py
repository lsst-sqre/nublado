"""Gafaelfawr authenticator for JupyterHub."""

from __future__ import annotations

from typing import Any

from jupyterhub.app import JupyterHub
from jupyterhub.auth import Authenticator
from jupyterhub.handlers import BaseHandler, LogoutHandler
from jupyterhub.user import User
from jupyterhub.utils import url_path_join
from tornado.httputil import HTTPHeaders
from tornado.web import HTTPError, RequestHandler

AuthInfo = dict[str, str | dict[str, str]]
Route = tuple[str, type[BaseHandler]]

__all__ = ["GafaelfawrAuthenticator"]


def _build_auth_info(headers: HTTPHeaders) -> AuthInfo:
    """Construct the authentication information for a user.

    Gafaelfawr puts the username in ``X-Auth-Request-User`` and the delegated
    notebook token in ``X-Auth-Request-Token``. Use those headers to construct
    a valid JupyterHub ``auth_state``.
    """
    username = headers.get("X-Auth-Request-User")
    token = headers.get("X-Auth-Request-Token")
    if not username or not token:
        raise HTTPError(401, "User is not authenticated")
    return {"name": username, "auth_state": {"token": token}}


class _GafaelfawrLogoutHandler(LogoutHandler):
    """Logout handler for Gafaelfawr authentication.

    A logout should always stop all running servers, and then redirect to the
    RSP logout page.
    """

    @property
    def shutdown_on_logout(self) -> bool:
        """Unconditionally true for Gafaelfawr logout."""
        return True

    async def render_logout_page(self) -> None:
        self.redirect("/logout", permanent=False)


class _GafaelfawrLoginHandler(BaseHandler):
    """Login handler for Gafaelfawr authentication.

    This retrieves the authentication token from the headers, makes an API
    call to get its metadata, constructs an authentication state, and then
    redirects to the next URL.
    """

    async def get(self) -> None:
        """Handle GET to the login page."""
        auth_info = _build_auth_info(self.request.headers)

        # Store the ancillary user information in the user database and create
        # or return the user object. This call is unfortunately undocumented,
        # but it's what BaseHandler calls to record the auth_state information
        # after a form-based login. Hopefully this is a stable interface.
        user = await self.auth_to_user(auth_info)

        # Tell JupyterHub to set its login cookie (also undocumented).
        self.set_login_cookie(user)

        # Redirect to the next URL, which is under the control of JupyterHub
        # and opaque to the authenticator. In practice, it will normally be
        # whatever URL the user was trying to go to when JupyterHub decided
        # they needed to be authenticated.
        self.redirect(self.get_next_url(user))


class GafaelfawrAuthenticator(Authenticator):
    """JupyterHub authenticator using Gafaelfawr headers.

    Rather than implement any authentication logic inside of JupyterHub,
    authentication is done via an ``auth_request`` handler made by the NGINX
    ingress controller. JupyterHub then only needs to read the authentication
    results from the headers of the incoming request.

    Normally, the authentication flow for JupyterHub is to send the user to
    ``/hub/login`` and display a login form. The submitted values to the form
    are then passed to the ``authenticate`` method of the authenticator, which
    is responsible for returning authentication information for the user.
    That information is then stored in an authentication session and the user
    is redirected to whatever page they were trying to go to.

    We however do not want to display an interactive form, since the
    authentication information is already present in the headers. We just need
    JupyterHub to read it.

    The documented way to do this is to register a custom login handler on a
    new route not otherwise used by JupyterHub, and then enable the
    ``auto_login`` setting on the configured authenticator. This setting tells
    the built-in login page to, instead of presenting a login form, redirect
    the user to whatever URL is returned by ``login_url``. In our case, this
    will be ``/hub/gafaelfawr/login``. This simple handler will read the token
    from the header, retrieve its metadata, create the session and cookie, and
    then make the same redirect call the login form handler would normally
    have made after the ``authenticate`` method returned.

    In this model, the ``authenticate`` method is not used, since the login
    handler never receives a form submission.

    Notes
    -----
    A possible alternative implementation that seems to be supported by the
    JupyterHub code would be to not override ``login_url``, set
    ``auto_login``, and then override ``get_authenticated_user`` in the
    authenticator to read authentication information directly from the request
    headers. It looks like an authenticator configured in that way would
    authenticate the user "in place" in the handler of whatever page the user
    first went to, without any redirects. This would be slightly more
    efficient and the code appears to handle it, but the current documentation
    (as of 1.5.0) explicitly says to not override ``get_authenticated_user``.

    This implementation therefore takes the well-documented path of a new
    handler and a redirect from the built-in login handler, on the theory that
    a few extra redirects is a small price to pay for staying within the
    supported and expected interface.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        # Automatically log in rather than prompting the user with a link.
        self.auto_login = True

        # Enable secure storage of auth state, which we'll use to stash the
        # user's token and pass it to the spawned pod.
        self.enable_auth_state = True

        # Refresh the auth state before spawning to ensure we have the user's
        # most recent token and group information.
        self.refresh_pre_spawn = True

        # Any authenticated user is allowed.  That, after all, is the point of
        # this class.  If Gafaelfawr says you are authenticated, and have the
        # right scope, we let you in.
        self.allow_all = True

    async def authenticate(
        self, handler: RequestHandler, data: dict[str, str]
    ) -> str | dict[str, Any] | None:
        """Login form authenticator.

        This is not used in our authentication scheme.

        Parameters
        ----------
        handler
            Tornado request handler.
        data
            Form data submitted during login.

        Raises
        ------
        NotImplementedError
            Raised if called.
        """
        raise NotImplementedError

    def get_handlers(self, app: JupyterHub) -> list[Route]:
        """Register the header-only login and the logout handlers.

        Parameters
        ----------
        app
            Tornado app in which to register the handlers.

        Returns
        -------
        list of tuple
            Additional routes to add.
        """
        return [
            ("/gafaelfawr/login", _GafaelfawrLoginHandler),
            ("/logout", _GafaelfawrLogoutHandler),
        ]

    def login_url(self, base_url: str) -> str:
        """Override the login URL.

        This must be changed to something other than ``/login`` to trigger
        correct behavior when ``auto_login`` is set to true (as it is in our
        case).

        Parameters
        ----------
        base_url
            Base URL of this JupyterHub installation.

        Returns
        -------
        str
            URL to which the user is sent during login. For this
            authenticator, this is a URL provided by a login handler that
            looks at headers set by Gafaelfawr_.
        """
        return url_path_join(base_url, "gafaelfawr/login")

    async def refresh_user(
        self, user: User, handler: RequestHandler | None = None
    ) -> bool | AuthInfo:
        """Optionally refresh the user's token.

        Parameters
        ----------
        user
            JupyterHub user information.
        handler
            Tornado request handler.

        Returns
        -------
        bool or dict
            Returns `True` if we cannot refresh the auth state and should
            use the existing state. Otherwise, returns the new auth state
            taken from the request headers set by Gafaelfawr_.

        Raises
        ------
        tornado.web.HTTPError
            Raised with a 401 error if the username does not match our current
            auth state, since JupyterHub does not support changing users
            during refresh.
        """
        # If running outside of a Tornado handler, we can't refresh the auth
        # state, so assume that it is okay.
        if not handler:
            return True

        # If there is no X-Auth-Request-Token header, this request did not go
        # through the Hub ingress and thus is coming from inside the cluster,
        # such as requests to JupyterHub from a JupyterLab instance. Allow
        # JupyterHub to use its normal authentication logic.
        token = handler.request.headers.get("X-Auth-Request-Token")
        if not token:
            return True

        # JupyterHub doesn't support changing the username of a user during
        # refresh, so if the username doesn't match what we're expecting,
        # raise a 401 error and force the user to reauthenticate. This can
        # happen if the user's username was changed underneath us.
        username = handler.request.headers.get("X-Auth-Request-User")
        if not username or user.name != username:
            raise HTTPError(401, "Username does not match expected identity")

        # We have a new token. If it doesn't match the token we have stored,
        # replace the stored auth state with the new auth state.
        auth_state = await user.get_auth_state()
        if token == auth_state.get("token"):
            return True
        else:
            return _build_auth_info(handler.request.headers)
