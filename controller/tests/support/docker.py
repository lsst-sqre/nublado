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
    ) -> None:
        self.tags = tags
        self._username = credentials.username
        self._password = credentials.password
        self._require_bearer = require_bearer
        self._token = os.urandom(16).hex()

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
        return Response(200, json={"tags": list(self.tags.keys())})

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
            404 if it is not, and 401 with an authentication challenge if not
            authenticated.
        """
        if not self._check_auth(request):
            return self._make_auth_challenge()
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
    *,
    host: str,
    repository: str,
    credentials_path: Path,
    tags: dict[str, str],
    require_bearer: bool = False,
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
        tags, auth_url, credentials, require_bearer=require_bearer
    )

    respx_mock.get(base_url + "/auth").mock(side_effect=mock.authenticate)
    respx_mock.get(tags_url).mock(side_effect=mock.list_tags)
    respx_mock.head(url__regex=digest_url).mock(side_effect=mock.get_digest)
    return mock
