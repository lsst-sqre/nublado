"""Mock out the Docker registry API for tests."""

from __future__ import annotations

import os
from base64 import b64decode, b64encode
from pathlib import Path
from urllib.parse import parse_qsl

import respx
from httpx import Request, Response

from controller.models.domain.docker import DockerCredentials
from controller.storage.docker import DockerCredentialStore

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
        Whether to paginate responses with Link header (GHCR does, but
        Docker Hub does not).
    duplicate_url
        Whether to (incorrectly) return the same "next" tag multiple times when
        paginating.  This is only used to test error-handling functionality
        in the tag-handling code, and only makes sense with paginate.
    netloc_paginate
        Whether to return a URL with a scheme and netloc when paginating
        (GHCR does not).  This only makes sense with paginate.


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
        # the authentication route.  These are the parameters that we return
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
        if not self._paginate:
            return Response(200, json={"tags": list(self.tags.keys())})
        return self._return_paginated_response(request)

    def _return_paginated_response(self, request: Request) -> Response:
        # We use an unrealistically small pagination size of 3 tags,
        # to exercise the pagination code.
        #
        # The pagination strategy is the same as ghcr.io uses, where
        # on subsequent calls, you tell it the last tag you saw, and
        # it starts from just past there when returning the next list.
        #
        # Since Docker Hub doesn't paginate tags at all, this is the
        # most realistic use case for us since we also use ghcr.io.
        # Nexus uses an opaque continuation token.
        p_size = 3
        tags = list(self.tags.keys())  # We want a list, not a set.
        initial_idx = 0

        query = request.url.query
        last_tag = ""
        if query:
            p_list = parse_qsl(query)
            for item in p_list:
                if item[0].decode() == "last":
                    last_tag = item[1].decode()
                    break
        if last_tag:
            # Let the ValueError propagate
            initial_idx = tags.index(last_tag) + 1
        these_tags = tags[initial_idx : initial_idx + p_size]
        resp_json = {"tags": these_tags}
        if initial_idx + p_size >= len(tags):
            # No next link; we've run out of tags.
            return Response(200, json=resp_json)
        target = request.url.path
        target = target if target.startswith("/") else f"/{target}"
        if self._netloc_paginate:
            # We're just ignoring port for testing purposes and assuming
            # scheme is 'https'.  The actual code does the latter too.
            target = f"https://{request.url.host}{target}"
        if self._duplicate_url:
            # Return a link to the base URL, to simulate a faulty registry
            # that sends you on an infinite loop when paginating tags.
            next_link = f'<{target}>; rel="next"'
        else:
            # n=0 is what we get from ghcr in the wild.  Setting it
            # does indeed seem to select a page size, and 0 means
            # "maximum", which means 100 in mid-October 2025.
            next_link = f'<{target}?last={these_tags[-1]}&n=0>; rel="next"'
        return Response(200, json=resp_json, headers={"Link": next_link})

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
        if not self._check_appropriate_accept(request):
            return Response(404)
        if tag in self.tags:
            return Response(
                200, headers={"Docker-Content-Digest": self.tags[tag]}
            )
        else:
            return Response(404)

    @staticmethod
    def _check_appropriate_accept(request: Request) -> bool:
        """Make sure that an Accept header allowing multi-architecture
        manifests is present.

        What we actually send from the client is all of these, and then
        `application/json` at a lower quality factor, to accomodate older
        registries that don't know about multi-architecture builds.
        """
        accept = request.headers.get("Accept")
        allowed = (
            "application/vnd.docker.distribution.manifest.v2+json",
            "application/vnd.docker.distribution.manifest.list.v2+json",
            "application/vnd.oci.image.manifest.v1+json",
            "application/vnd.oci.image.index.v1+json",
        )
        if accept:
            alternatives = accept.split(",")
            for alt in alternatives:
                # Strip any attributes
                acc = alt[:pos] if (pos := alt.find(";") > -1) else alt
                if acc in allowed:
                    # Succeed at first match
                    return True
        # We did not get any of the multi-arch Accept: headers.
        return False

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
    *,
    host: str,
    repository: str,
    credentials_path: Path,
    tags: dict[str, str],
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
    host
        The hostname on which the mock API should appear to listen.
    repository
        The name of the repository (like ``lsstsqre/sciplat-lab``) for which
        to register the mocks.
    credentials_path
        Path to a Docker credentials store.
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
    base_url = f"https://{host}"
    auth_url = f"{base_url}/auth"
    tags_url = f"{base_url}/v2/{repository}/tags/list"
    digest_url = f"{base_url}/v2/{repository}/manifests/(?P<tag>.*)"

    store = DockerCredentialStore.from_path(credentials_path)
    credentials = store.get(host)
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
