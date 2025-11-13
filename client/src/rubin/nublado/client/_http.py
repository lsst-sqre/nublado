"""HTTP client wrapper for talking to JupyterHub and JupyterLab."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Coroutine
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from functools import wraps
from typing import Any, Concatenate, Literal
from urllib.parse import urljoin, urlparse

import websockets
from httpx import AsyncClient, Cookies, HTTPError, Response, Timeout
from httpx_sse import EventSource, aconnect_sse
from rubin.repertoire import DiscoveryClient
from structlog.stdlib import BoundLogger
from websockets.asyncio.client import ClientConnection

from ._exceptions import (
    NubladoDiscoveryError,
    NubladoRedirectError,
    NubladoWebError,
)

type SecFetchMode = Literal[
    "cors", "navigate", "no-cors", "same-origin", "websocket"
]

__all__ = ["JupyterAsyncClient"]


def _convert_exception[**P, T](
    f: Callable[Concatenate[JupyterAsyncClient, P], Coroutine[None, None, T]],
) -> Callable[Concatenate[JupyterAsyncClient, P], Coroutine[None, None, T]]:
    """Convert HTTPX exceptions to Nublado exceptions."""

    @wraps(f)
    async def wrapper(
        client: JupyterAsyncClient, *args: P.args, **kwargs: P.kwargs
    ) -> T:
        start = datetime.now(tz=UTC)
        try:
            return await f(client, *args, **kwargs)
        except HTTPError as e:
            username = client._username  # noqa: SLF001
            exc = NubladoWebError.from_exception(e, username)
            exc.started_at = start
            raise exc from e

    return wrapper


class JupyterAsyncClient:
    """Wrapper around an HTTP client with JupyterHub and JupyterLab support.

    The Nublado client, rather than using Jupyter access tokens, simulates a
    web browser when interacting with JupyterHub and JupyterLab. This requires
    some special handling:

    - An ``Authorization`` header must be set on every request to get past
      Gafaelfawr authentication.
    - The client needs a persistent cookie jar to handle XSRF cookies.
    - An additional ``X-XSRFToken`` header must be added to requests
      containing the XSRF token. (This is easier than trying to inject it
      into the query string or POST body.)
    - The XSRF token for the ``X-XSRFToken`` header must be extracted from
      the cookie jar, but it may only be present in some intermediate
      responses in redirect chains.
    - ``Sec-Fetch-Mode`` must be set to appropriate values on different
      requests to avoid annoying logs messages or XSRF validation failures.

    This wrapper around an HTTPX ``AsyncClient`` handles that complexity and
    exposes a simple API to the rest of the Nublado client.

    Parameters
    ----------
    discovery_client
        Repertoire discovery client, used to find the base URL of JupyterHub.
    logger
        Logger to use.
    timeout
        Timeout to use when talking to JupyterHub and JupyterLab. This is
        used as a connection, read, and write timeout for all regular HTTP
        calls.
    token
        Gafaelfawr token to use for authentication.
    username
        Username on whose behalf the client will be acting.
    """

    def __init__(
        self,
        *,
        discovery_client: DiscoveryClient,
        logger: BoundLogger,
        timeout: timedelta,
        token: str,
        username: str,
    ) -> None:
        self._discovery = discovery_client
        self._token = token
        self._logger = logger
        self._username = username

        # Every instance of this client uses a separate HTTPX AsyncClient so
        # that it has a separate cookie jar, since the cookies set by
        # JupyterHub and JupyterLab are user-specific and would overwrite each
        # other if the same client were reused.
        self._client = AsyncClient(timeout=timeout.total_seconds())

        # Base URL of the user's lab, or None if not yet determined.
        self._lab_base_url: str | None = None

        # Discovered XSRF tokens, or None if not yet determined.
        self._hub_xsrf: str | None = None
        self._lab_xsrf: str | None = None

    async def aclose(self) -> None:
        """Close the underlying HTTP connection pool.

        This invalidates the client object. It can no longer be used after
        this method is called.
        """
        await self._client.aclose()

    @_convert_exception
    async def delete(
        self, route: str, *, add_referer: bool = False
    ) -> Response:
        """Perform a DELETE request to JupyterHub or JupyterLab.

        Parameters
        ----------
        route
            Route relative to the base URL of Nublado. Routes starting with
            ``user`` are considered JupyterLab routes.
        add_referer
            Whether to add a ``Referer`` header pointing to the JupyterHub
            home page. This is required by JupyterHub in some cases.

        Returns
        -------
        httpx.Response
            HTTP response at the end of any redirect chain.

        Raises
        ------
        NubladoDiscoveryError
            Raised if Nublado is missing from service discovery.
        NubladoWebError
            Raised if there were HTTP errors talking to Nublado.
        rubin.repertoire.RepertoireError
            Raised if there was an error talking to service discovery.
        """
        url = await self._url_for(route)
        headers = await self._headers_for(route, add_referer=add_referer)
        r = await self._client.delete(url, headers=headers)
        r.raise_for_status()
        return r

    @_convert_exception
    async def get(
        self,
        route: str,
        *,
        add_referer: bool = False,
        fetch_mode: SecFetchMode = "same-origin",
    ) -> Response:
        """Perform a GET request to JupyterHub or JupyterLab.

        Handles authentication and redirect following, ensuring that the
        redirects are relative to either the JupyterHub or JupyterLab base
        URLs.

        Parameters
        ----------
        route
            Route relative to the base URL of Nublado. Routes starting with
            ``user`` are considered JupyterLab routes.
        add_referer
            Whether to add a ``Referer`` header pointing to the JupyterHub
            home page. This is required by JupyterHub in some cases.
        fetch_mode
            Value of ``Sec-Fetch-Mode`` header to send. This suppresses some
            log noise and improves XSRF handling in JupyterHub and JupyterLab.

        Returns
        -------
        httpx.Response
            HTTP response at the end of any redirect chain.

        Raises
        ------
        NubladoDiscoveryError
            Raised if Nublado is missing from service discovery.
        NubladoRedirectError
            Raised if the URL is outside of Nublado's URL space or there is a
            redirect loop.
        NubladoWebError
            Raised if there were HTTP errors talking to Nublado.
        rubin.repertoire.RepertoireError
            Raised if there was an error talking to service discovery.
        """
        url = await self._url_for(route)
        headers = await self._headers_for(route, fetch_mode=fetch_mode)
        return await self._get(url, headers)

    @_convert_exception
    async def open_sse_stream(
        self, route: str
    ) -> AbstractAsyncContextManager[EventSource]:
        """Open a server-sent events stream.

        Parameters
        ----------
        route
            Route relative to the base URL of Nublado. Routes starting with
            ``user`` are considered JupyterLab routes.

        Returns
        -------
        contextlib.AbstractAsyncContextManager
            Context manager that provides an ``httpx_sse.EventSource``.

        Raises
        ------
        NubladoDiscoveryError
            Raised if Nublado is missing from service discovery.
        NubladoWebError
            Raised if there were HTTP errors talking to Nublado.
        rubin.repertoire.RepertoireError
            Raised if there was an error talking to service discovery.
        """
        url = await self._url_for(route)
        headers = await self._headers_for(route, add_referer=True)
        return aconnect_sse(self._client, "GET", url, headers=headers)

    @_convert_exception
    async def open_websocket(
        self,
        route: str,
        *,
        open_timeout: timedelta,
        max_size: int | None,
    ) -> AbstractAsyncContextManager[ClientConnection]:
        """Open a WebSocket connection.

        Parameters
        ----------
        route
            Route relative to the base URL of Nublado. Routes starting with
            ``user`` are considered JupyterLab routes.
        max_size
            Maximum size of a WebSocket message, or `None` for no limit.

        Returns
        -------
        contextlib.AbstractAsyncContextManager
            Context manager that provides a
            `~websockets.asyncio.client.ClientConnection`.

        Raises
        ------
        NubladoDiscoveryError
            Raised if Nublado is missing from service discovery.
        NubladoRedirectError
            Raised if the URL is outside of Nublado's URL space or there is a
            redirect loop.
        rubin.repertoire.RepertoireError
            Raised if there was an error talking to service discovery.
        """
        url = await self._url_for(route)
        headers = await self._headers_for(route)
        request = self._client.build_request("GET", url, headers=headers)
        headers["Cookie"] = request.headers["Cookie"]
        return websockets.connect(
            self._url_for_websocket(url),
            additional_headers=headers,
            open_timeout=open_timeout.total_seconds(),
            max_size=max_size,
        )

    @_convert_exception
    async def post(
        self,
        route: str,
        *,
        content: str | None = None,
        data: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        timeout: Timeout | None = None,
        add_referer: bool = False,
        extra_headers: dict[str, str] | None = None,
    ) -> Response:
        """Perform a POST request to JupyterHub or JupyterLab.

        Follows redirects in the response using GET requests.

        Parameters
        ----------
        route
            Route relative to the base URL of Nublado. Routes starting with
            ``user`` are considered JupyterLab routes.
        contents
            Raw contents for the POST body. Only one of ``contents``,
            ``data``, or ``json`` may be specified.
        data
            Data for the POST body. Only one of ``contents``, ``data``, or
            ``json`` may be specified.
        json
            Data for a POST body formatted as JSON. Only one of ``contents``,
            ``data``, or ``json`` may be specified.
        timeout
            HTTPX timeout settings, overriding the defaults.
        add_referer
            Whether to add a ``Referer`` header pointing to the JupyterHub
            home page. This is required by JupyterHub in some cases.
        extra_headers
            Additional headers to add to the request. These headers should not
            conflict with the standard headers; if they do, the values in
            ``extra_headers`` will override the standard headers, which will
            probably break.

        Returns
        -------
        httpx.Response
            HTTP response at the end of any redirect chain.

        Raises
        ------
        NubladoDiscoveryError
            Raised if Nublado is missing from service discovery.
        NubladoRedirectError
            Raised if the URL is outside of Nublado's URL space or there is a
            redirect loop.
        NubladoWebError
            Raised if there were HTTP errors talking to Nublado.
        rubin.repertoire.RepertoireError
            Raised if there was an error talking to service discovery.
        """
        url = await self._url_for(route)
        headers = await self._headers_for(route, fetch_mode="same-origin")
        if extra_headers:
            headers.update(extra_headers)
        r = await self._client.post(
            url,
            headers=headers,
            content=content,
            data=data,
            json=json,
            timeout=timeout,
        )
        if r.is_redirect:
            next_url = urljoin(url, r.headers["Location"])
            await self._check_redirect(next_url)
            return await self._get(next_url, headers)
        r.raise_for_status()
        return r

    async def _check_redirect(
        self, url: str, lab_base_url: str | None = None
    ) -> None:
        """Check that a URL is within Nublado's URL space.

        Parameters
        ----------
        url
            URL from redirect after canonicalization.
        lab_base_url
            If set, overrides the discovered lab base URL.

        Raises
        ------
        NubladoRedirectError
            Raised if the URL is outside of Nublado's URL space.
        """
        hub_url = await self._hub_base_url()
        if url.startswith(hub_url):
            return
        lab_base_url = lab_base_url or self._lab_base_url
        if lab_base_url and url.startswith(lab_base_url):
            return
        raise NubladoRedirectError("Unexpected redirect", url)

    def _extract_xsrf(
        self, response: Response, lab_base_url: str | None = None
    ) -> None:
        """Extract the XSRF token from the cookies in a response.

        Parameters
        ----------
        response
            Response from a Jupyter server.
        lab_base_url
            If set, overrides the discovered lab base URL.
        """
        if not lab_base_url:
            lab_base_url = self._lab_base_url
        if lab_base_url:
            prefix = lab_base_url + "/user"
            is_lab = str(response.url).startswith(prefix)
        else:
            is_lab = False
        current = self._lab_xsrf if is_lab else self._hub_xsrf

        # Load the cookies from the response.
        cookies = Cookies()
        cookies.extract_cookies(response)

        # If there is an _xsrf cookie and it's different than the one we
        # currently have stored, update our cookie.
        xsrf = cookies.get("_xsrf")
        if xsrf and xsrf != current:
            service = "JupyterLab" if is_lab else "JupyterHub"
            self._logger.debug(
                f"Found new _xsrf cookie for {service}",
                method=response.request.method,
                url=str(response.url.copy_with(query=None, fragment=None)),
                status_code=response.status_code,
            )
            if is_lab:
                self._lab_xsrf = xsrf
            else:
                self._hub_xsrf = xsrf

    async def _find_lab_base_url(self) -> str:
        """Find the base URL of the user's JupyterLab.

        Request the top-level JupyterLab page under the JupyterHub domain. If
        per-user subdomains are not in use, this will be the main JupyterLab
        page. If they are in use, this will result in a redirect to the true
        JupyterLab domain, which is then remembered for further use.

        Returns
        -------
        str
            Base URL of the user's JupyterLab.

        Raises
        ------
        NubladoDiscoveryError
            Raised if Nublado is missing from service discovery.
        NubladoRedirectError
            Raised if the URL is outside of Nublado's URL space or there is a
            redirect loop.
        NubladoWebError
            Raised if there were HTTP errors trying to find the base URL fo
            the user's lab.
        rubin.repertoire.RepertoireError
            Raised if there was an error talking to service discovery.
        """
        base_url = await self._hub_base_url()
        route = f"user/{self._username}/lab"
        next_url = f"{base_url}/{route}"
        headers = await self._headers_for(route, fetch_mode="navigate")

        # Now, follow each redirect looking for changed hostnames and XSRF
        # cookies. The seen URL tracking, to prevent redirect loops, has to
        # allow visiting a given URL twice since there may be an OAuth
        # authentication that returns the user to the previous URL.
        host_prefix = f"{self._username}."
        seen = Counter(next_url)
        r = await self._client.get(next_url, headers=headers)
        while r.is_redirect:
            location = r.headers["Location"]
            msg = "Redirect from lab"
            self._logger.debug(msg, url=next_url, redirect=location)

            # If redirected to a different hostname that starts with the
            # username, update _lab_base_url accordingly. This is not always
            # the first redirect because a JupyterHub authentication may be
            # required first.
            new = urlparse(location)
            if new.hostname and new.hostname.startswith(host_prefix):
                current = urlparse(base_url)
                if current.netloc != new.netloc:
                    base_url = current._replace(netloc=new.netloc).geturl()
                    msg = "Found JupyterLab base URL"
                    self._logger.debug(msg, base_url=base_url)

            # Now we can check the location to ensure that we weren't
            # redirected outside of the Nublado URL space. This has a small
            # flaw in that we accept redirects that start with the username,
            # but that's unavoidable since we don't know the per-user
            # subdomain hostname.
            next_url = urljoin(next_url, location)
            await self._check_redirect(next_url, lab_base_url=base_url)
            if seen[next_url] > 1:
                raise NubladoRedirectError("Redirect loop", next_url)
            seen[next_url] += 1

            # Check for and update the XSRF token if needed and then follow
            # the redirect.
            self._extract_xsrf(r, lab_base_url=base_url)
            r = await self._client.get(next_url, headers=headers)

        # No more redirects. Ensure we got success, again extract the XSRF
        # token if needed, and return the result.
        r.raise_for_status()
        self._extract_xsrf(r)
        return base_url

    async def _get(self, url: str, headers: dict[str, str]) -> Response:
        """Get a URL, following redirects and extracting XSRF tokens.

        Parameters
        ----------
        url
            URL to retrieve.
        headers
            Additional headers to send.

        Returns
        -------
        Response
            HTTP response.

        Raises
        ------
        NubladoDiscoveryError
            Raised if Nublado is missing from service discovery.
        NubladoRedirectError
            Raised if the URL is outside of Nublado's URL space or there is a
            redirect loop.
        NubladoWebError
            Raised if there were HTTP errors talking to Nublado.
        rubin.repertoire.RepertoireError
            Raised if there was an error talking to service discovery.
        """
        r = await self._client.get(url, headers=headers)
        seen = Counter(url)
        while r.is_redirect:
            self._extract_xsrf(r)
            url = urljoin(url, r.headers["Location"])
            await self._check_redirect(url)
            if seen[url] > 1:
                raise NubladoRedirectError("Redirect loop", url)
            seen[url] += 1
            r = await self._client.get(url, headers=headers)
        r.raise_for_status()
        self._extract_xsrf(r)
        return r

    async def _headers_for(
        self,
        route: str,
        *,
        add_referer: bool = False,
        fetch_mode: SecFetchMode = "same-origin",
    ) -> dict[str, str]:
        """Construct the HTTP headers for a request.

        Parameters
        ----------
        route
            Route of the request, relative to the JupyterHub or JupyterLab
            base URL. Routes starting with ``user/`` will be considered
            JupyterLab routes.
        fetch_mode
            Value of ``Sec-Fetch-Mode`` header to set.

        Returns
        -------
        dict of str
            HTTP headers to send in the request.
        """
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Sec-Fetch-Mode": fetch_mode,
        }
        if route.startswith("user/"):
            if self._lab_xsrf:
                headers["X-XSRFToken"] = self._lab_xsrf
        elif self._hub_xsrf:
            headers["X-XSRFToken"] = self._hub_xsrf
        if add_referer:
            headers["Referer"] = await self._url_for("hub/home")
        return headers

    async def _hub_base_url(self) -> str:
        """Get the base URL of JupyterHub.

        Returns
        -------
        str
            Base URL for JupyterHub, without any trailing slashes.

        Raises
        ------
        NubladoDiscoveryError
            Raised if Nublado is missing from service discovery.
        rubin.repertoire.RepertoireError
            Raised if there was an error talking to service discovery.
        """
        hub_url = await self._discovery.url_for_ui("nublado")
        if not hub_url:
            msg = "nublado service not found in service discovery"
            raise NubladoDiscoveryError(msg)
        return hub_url.rstrip("/")

    async def _url_for(self, route: str) -> str:
        """Construct a JupyterHub or JupyterLab URL from a route.

        Uses service discovery to find the base URL except for routes starting
        with ``user``. In that case, the route is for the user's lab, and
        therefore must use the lab base URL, which may be in a different
        domain.

        Dynamically discover the lab base URL if it is not known by going to
        the main user lab page via GET first, since POST to the lab must start
        from the correct URL.

        Parameters
        ----------
        route
            Route relative to the base URL for Nublado. Must not start with
            ``/``.

        Returns
        -------
        str
            Full URL to use.

        Raises
        ------
        NubladoDiscoveryError
            Raised if Nublado is missing from service discovery.
        NubladoRedirectError
            Raised if the URL is outside of Nublado's URL space.
        NubladoWebError
            Raised if there were HTTP errors trying to find the base URL fo
            the user's lab.
        rubin.repertoire.RepertoireError
            Raised if there was an error talking to service discovery.
        """
        if route.startswith("user/"):
            if not self._lab_base_url:
                self._lab_base_url = await self._find_lab_base_url()
            return f"{self._lab_base_url}/{route}"

        # Remaining cases are URLs at JupyterHub and should use service
        # discovery.
        hub_url = await self._hub_base_url()
        return f"{hub_url}/{route}"

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
