"""Mock out the Docker registry API for tests."""

import os
from base64 import b64decode, b64encode
from urllib.parse import parse_qs, parse_qsl

import respx
from httpx import Request, Response

from nublado.controller.models.domain.docker import DockerCredentials
from nublado.controller.models.v1.prepuller import DockerSourceOptions
from nublado.controller.storage.docker import DockerCredentialStore

__all__ = ["MockDockerRegistry", "register_mock_docker"]


class MockDockerRegistry:
    """Mock Docker registry that returns tags and image digests.

    Parameters
    ----------
    tags
        Map of tag names to image digests.
    realm
        Realm for authentication challenge.
    credentials
        Credentials to expect for authentication.
    require_bearer
        Whether to require bearer token authentication, which requires another
        round trip to exchange the username and password for a bearer token.
    paginate
        Whether to paginate responses with ``Link`` header.
    duplicate_url
        Whether to (incorrectly) return the same ``next`` tag multiple times
        when paginating. This is only used to test error-handling
        functionality in the tag-handling code, and only makes sense with
        paginate.
    netloc_paginate
        Whether to return a URL with a scheme and netloc when paginating (GHCR
        does not). This only makes sense with paginate.

    Attributes
    ----------
    tags
        Map of tag names to image digests.
    """

    def __init__(
        self,
        tags: dict[str, str],
        realm: str,
        credentials: DockerCredentials,
        *,
        require_bearer: bool = False,
        paginate: bool = False,
        duplicate_url: bool = False,
        netloc_paginate: bool = False,
    ) -> None:
        self.tags = tags
        self._username = credentials.username
        self._password = credentials.password
        self._require_bearer = require_bearer
        self._paginate = paginate
        self._duplicate_url = duplicate_url if paginate else False
        self._netloc_paginate = netloc_paginate if paginate else False
        self._token = os.urandom(16).hex()
        self._tagindex = 0

        # The token authentication protocol for the Docker API returns
        # parameters in the WWW-Authenticate header that should be passed into
        # the authentication route. These are the parameters that we return
        # and then expect.
        self._challenge = {
            "realm": realm,
            "service": "registry.docker.io",
            "scope": "repository:pull",
        }

    def authenticate(self, request: Request) -> Response:
        """Simulate authentication URL for a Docker registry.

        Parameters
        ----------
        request
            Incoming request.

        Returns
        -------
        httpx.Response
            Returns 200 with an authentication token in the body.
        """
        params = parse_qsl(request.url.query.decode())
        assert sorted(params) == sorted(self._challenge.items())
        auth = f"{self._username}:{self._password}".encode()
        auth_b64 = b64encode(auth).decode()
        auth_type, auth_data = request.headers["Authorization"].split(None, 1)
        assert auth_type.lower() == "basic"
        assert auth_data == auth_b64
        return Response(200, json={"token": self._token})

    def list_tags(self, request: Request) -> Response:
        """Simulate the list tags route for a Docker Registry.

        This does not distinguish between different image repositories or
        names.  The same tag list is returned for all of them.

        Parameters
        ----------
        request
            Incoming request.

        Returns
        -------
        httpx.Response
            Returns 200 with the tag list if authenticated, otherwise 401 with
            an authentication challenge.
        """
        if not self._check_auth(request):
            return self._make_auth_challenge()
        if self._paginate:
            return self._return_paginated_response(request)
        else:
            return Response(200, json={"tags": list(self.tags.keys())})

    def _return_paginated_response(self, request: Request) -> Response:
        """Paginate the tags based on the request parameters.

        Split the list of tags in half, and on first response, return the
        first half (or slightly less, if there are an odd number of tags). and
        when given a page parameter, return the rest.

        Parameters
        ----------
        request
            Incoming request.

        Returns
        -------
            Returns 200 with the relevant portion of the tag list given the
            request.

        Notes
        -----
        Actual Docker registries behave differently. ghcr.io tells you the
        last tag it gave you, you tell it that was the last one you saw on the
        previous call, and it starts from just past there in its list when
        giving you the next set of tags.

        Docker Hub doesn't paginate tags at all, at least out to the
        1500-ish tags range.

        Nexus uses an opaque continuation token that presumably maps to a
        checksum of some pointer into its list of tags.
        """
        tags = list(self.tags.keys())
        midpoint = int(len(tags) / 2)

        # The only parameter we should see is page, which must be 2 to get the
        # second page. Any other value is incorrect.
        if request.url.query:
            query = parse_qs(request.url.query.decode())
            assert query == {"page": ["2"]}
            return Response(200, json={"tags": tags[midpoint:]})

        # The request is for the first page. Do pagination. This will
        # construct a next URL that matches the current URL plus ?page=2 and
        # stick that in a link header.
        url = request.url.path
        if self._netloc_paginate:
            if not url.startswith("/"):
                url = "/" + url
            url = f"https://{request.url.host}{url}"
        if self._duplicate_url:
            link_header = f'<{url}>; rel="next"'
        else:
            link_header = f'<{url}?page=2>; rel="next"'
        result = {"tags": tags[:midpoint]}
        return Response(200, json=result, headers={"Link": link_header})

    def get_digest(self, request: Request, tag: str) -> Response:
        """Simulate the image manifest route for a Docker Registry.

        We only call this route with HEAD and expect the image digest to
        appear in the ``Docker-Content-Digest`` HTTP header.

        Parameters
        ----------
        request
            Incoming request.
        tag
            The tag for which the digest is requested, extracted from the URL.

        Returns
        -------
        httpx.Response
            Returns 200 with the digest in the header if the tag is known,
            404 if it is not or if the Accept: header does not specify an
            appropriate media type, and 401 with an authentication challenge
            if not authenticated.
        """
        if not self._check_auth(request):
            return self._make_auth_challenge()
        types = request.headers.get("Accept").split(", ")
        assert "application/vnd.docker.distribution.manifest.v2+json" in types
        if tag in self.tags:
            return Response(
                200, headers={"Docker-Content-Digest": self.tags[tag]}
            )
        else:
            return Response(404)

    def _check_auth(self, request: Request) -> bool:
        """Check whether the request is authenticated."""
        if "Authorization" not in request.headers:
            return False
        auth_type, auth_data = request.headers["Authorization"].split(None, 1)
        if self._require_bearer:
            if auth_type.lower() != "bearer":
                return False
            return auth_data == self._token
        else:
            if auth_type.lower() != "basic":
                return False
            username, password = b64decode(auth_data).decode().split(":", 1)
            return username == self._username and password == self._password

    def _make_auth_challenge(self) -> Response:
        """Construct an authentication challenge."""
        if self._require_bearer:
            challenge = "Bearer " + ",".join(
                f'{k}="{v}"' for k, v in self._challenge.items()
            )
        else:
            challenge = f'Basic realm="{self._challenge["realm"]}"'
        return Response(401, headers={"WWW-Authenticate": challenge})


def register_mock_docker(
    respx_mock: respx.Router,
    config: DockerSourceOptions,
    tags: dict[str, str],
    *,
    require_bearer: bool = False,
    paginate: bool = True,
    duplicate_url: bool = False,
    netloc_paginate: bool = False,
) -> MockDockerRegistry:
    """Mock out a Docker registry.

    Parameters
    ----------
    respx_mock
        Mock router.
    config
        Configuration for the Docker image source.
    tags
        A mapping of tags to image digests that should appear on that
        registry.
    require_bearer
        Whether to require bearer token authentication.
    paginate
        Whether to paginate responses with Link header (GHCR.io does, but
        Docker Hub does not).
    duplicate_url
        Whether to (incorrectly) return the same URL multiple times when
        paginating.  This is only used to test error-handling functionality
        in the tag-handling code.
    netloc_paginate
        Whether to return a URL with a scheme and netloc when paginating
        (GHCR does not).  This only makes sense with paginate.

    Returns
    -------
    MockDockerRegistry
        The mock Docker API object.
    """
    base_url = f"https://{config.registry}"
    auth_url = f"{base_url}/auth"
    tags_url = f"{base_url}/v2/{config.repository}/tags/list"
    digest_url = f"{base_url}/v2/{config.repository}/manifests/(?P<tag>.*)"

    store = DockerCredentialStore.from_path(config.credentials_path)
    credentials = store.get(config.registry)
    assert credentials
    mock = MockDockerRegistry(
        tags,
        auth_url,
        credentials,
        require_bearer=require_bearer,
        paginate=paginate,
        duplicate_url=duplicate_url,
        netloc_paginate=netloc_paginate,
    )

    respx_mock.get(base_url + "/auth").mock(side_effect=mock.authenticate)
    respx_mock.get(tags_url).mock(side_effect=mock.list_tags)
    respx_mock.head(url__regex=digest_url).mock(side_effect=mock.get_digest)
    return mock
