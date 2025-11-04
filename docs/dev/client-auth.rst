##################################################
Client authentication to JupyterHub and JupyterLab
##################################################

The Nublado client's authentication to JupyterHub and JupyterLab is highly complex and took considerable trial and error to develop.
This page provides an overview of how the code is currently structured, why it does what it does, and what assumptions it is making about the Jupyter code.

JupyterHub and, to a lesser extent, JupyterLab expects to be used in one of two ways: by a human using a web browser, or through its API using authentication tokens.
The Nublado client intentionally violates this assumption: It emulates a user without using a web browser, retrieving a mix of both the pages a user would access with a web browser and API endpoints.
This is the source of most of the complexity, but it also allows us to avoid managing admin tokens to JupyterHub and to use mobu_ to test a flow similar to what a user might use in a web browser.

Gafaelfawr authentication
=========================

Phalanx_ puts Gafaelfawr_ in front of all accesses to Nublado, either JupyterHub or JupyterLab (or other components).
This means the Nublado client must send a Gafaelfawr token with every request, alongside anything else required by JupyterHub or JupyterLab.
A user's web browser will normally have a Gafaelfawr session cookie, but there is currently no way to create such a cookie via an API without a full single sign-on provider interaction.
The Nublado client therefore sends an ``Authorization`` header with every request containing the Gafaelfawr token it was provided as a bearer token.

Note that this must be included on every request, including when following redirects, which are common when interacting with Jupyter.

Jupyter authentication
======================

JupyterHub in Nublado uses the Gafaelfawr plugin (`~rubin.nublado.authenticator.GafaelfawrAuthenticator`) for authentication.
This plugin redirects to a custom endpoint, extracts authentication information from the request headers (where it is put by Gafaelfawr), and then redirects the user back to the page where they were going.

JupyterLab uses OAuth 2 authentication with JupyterHub as the authentication provider.
This means that the first access to JupyterLab redirects the user back to a JupyterHub endpoint, where they follow the normal JupyterHub authentication process (usually cut short by the fact they already have an authentication cookie) and are then redirected back to JupyterLab to complete the OAuth 2 authentication and set an authentication cookie.

In both cases, authentication credentials are then stored in a cookie.
If per-user subdomains are used, these cookies are scoped to the appropriate domains.
JupyterHub's cookie will be set on, for example, the hostname ``nb.data.example.com``, and JupyterLab's cookie will be set for the hostname ``username.nb.data.example.com``.
If JupyterHub and JupyterLab are hosted in the same domain (not recommended for web security reasons), the JupyterLab cookies are path-scoped to only the routes that the proxy will send to JupyterLab.

Note that the cookies for different users should probably be assumed to conflict, so the client must use a separate client-side cookie jar for each user.
The Nublado client achieves this by creating a separate HTTPX_ ``AsyncClient`` for each user.

JupyterLab domain discovery
===========================

In the case where per-user subdomains are in use, the Nublado client cannot know the correct domain for JuypterLab in advance, since this is a configuration setting in JupyterHub.
Instead, it has to access the route for the lab (:samp:`user/{username}/lab`) on the JupyterHub domain and then see if that results (possibly after several redirects) in a redirect to a different domain that begins with the username.
If so, it can then record that domain as the correct domain for JupyterLab.
If there is no redirect, it assumes that JupyterLab is hosted on the same hostname as JupyterHub.

Determining the correct hostname for JupyterLab is required before opening a lab session, since opening a lab session is a POST call to a JupyterLab route.
If that results in a redirect, the POST will fail.

XSRF tokens
===========

In addition to the authentication cookies, JupyterHub and JuypterLab also use XSRF tokens to protect against cross-site attacks.
In both cases, the token is stored in a cookie named ``_xsrf`` and must also be included separately in most requests.
(Requiring only the cookie isn't sufficient to protect against XSRF.)
The Jupyter code supports three ways for the client to send the cookie: as a query parameter, in an ``X-XSRFToken`` HTTP header, or in an ``X-CSRFToken`` HTTP header.
Including it in the POST body may also be allowed in some cases.

The Nublado client always sends the XSRF token in the ``X-XSRFToken`` header.

One of the more challenging parts of the client's interaction is discovering this XSRF token.
JupyterHub and JupyterLab both set it in a cookie, but they both use the same cookie name and distinguish via path scoping in the case where they are both hosted on the same domain.
They also may not set the cookie on the first request, or may change the cookie's value after authentication.
Worse, the token may expire or be refreshed, in which case both JupyterHub and JupyterLab may set a replacement token that now must be sent instead.

The Nublado client therefore checks for ``_xsrf`` tokens on every request and uses the current route to determine whether that XSRF token is for JuypterHub or JupyterLab.
Each time it sees a new token, it records that token for the appropriate service, and includes it in an ``X-XSRFToken`` header for each request.

Referer and Sec-Fetch-Mode
==========================

JupyterHub has some other cross-site scripting defenses for URLs that it expects to only be accessed by web browsers.
These include some of the URLs that the Nublado client uses.

In some cases, requests may be rejected unless a ``Referer`` (note spelling; the header was misspelled in the standard and therefore must be spelled that way) header is sent, pointing to a valid JupyterHub page.
For those requests, the Nublado client sends a ``Referer`` header pointing to the JupyterHub home page.

JupyterHub and JupyterLab also inspects the ``Sec-Fetch-Mode`` header when checking the XSRF token.
This header is sent by web browsers and indicates the browser operation that resulted in the web page request.
The requests will succeed without this header, but will result in annoying warnings that clutter up the logs.

The Nublado client tries to set this header to a reasonable value for the type of page that it is accessing.
When retrieving pages that the user would access directly in the web browser, it sends a value of ``navigate``.
Otherwise, it sends the value ``same-site``.
This will hopefully suppress the warning messages in the logs.
