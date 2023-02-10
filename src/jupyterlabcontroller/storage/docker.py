"""Client for the Docker v2 API."""

import json
from pathlib import Path
from typing import Self

from httpx import AsyncClient, Response
from structlog.stdlib import BoundLogger

from ..exceptions import DockerRegistryError
from ..models.domain.docker import DockerCredentials


class DockerCredentialStore:
    """Read and write the ``.dockerconfigjson`` syntax used by Kubernetes."""

    @classmethod
    def from_path(cls, path: Path) -> Self:
        """Load credentials for Docker API hosts from a file.

        Parameters
        ----------
        path
            Path to file containing credentials.

        Returns
        -------
        DockerCredentialStore
            The resulting credential store.
        """
        with path.open("r") as f:
            credentials_data = json.load(f)
        credentials = {}
        for host, config in credentials_data["auths"].items():
            credentials[host] = DockerCredentials.from_config(host, config)
        return cls(credentials)

    def __init__(self, credentials: dict[str, DockerCredentials]) -> None:
        self._credentials = credentials

    def get(self, host: str) -> DockerCredentials | None:
        """Get credentials for a given host.

        These may be domain credentials, so if there is no exact match, return
        the credentials for any parent domain found.

        Parameters
        ----------
        host
            Host to which to authenticate.

        Returns
        -------
        jupyterlabcontroller.models.domain.docker.DockerCredentials or None
            The corresponding credentials or `None` if there are no
            credentials in the store for that host.
        """
        credentials = self._credentials.get(host)
        if credentials:
            return credentials
        for domain, credentials in self._credentials.items():
            if host.endswith(f".{domain}"):
                return credentials
        return None

    def save(self, path: Path) -> None:
        """Save the credentials store in ``.dockerconfigjson`` format.

        Parameters
        ----------
        path
            Path at which to save the credential store.
        """
        data = {
            "auths": {h: c.to_config() for h, c in self._credentials.items()}
        }
        with path.open("w") as f:
            json.dump(data, f)


class DockerStorageClient:
    """Client to query the Docker API for image information.

    Parameters
    ----------
    http_client
        Client to use to make requests.
    logger
        Logger for log messages.
    credentials
        Docker credential store to use for authentication.
    """

    def __init__(
        self,
        *,
        http_client: AsyncClient,
        logger: BoundLogger,
        credentials: DockerCredentialStore,
    ) -> None:
        self._client = http_client
        self._logger = logger
        self._credentials = credentials
        self._authorization: dict[str, str] = {}

    async def list_tags(self, registry: str, repository: str) -> list[str]:
        """List all the tags for a given registry and repository.

        Parameters
        ----------
        registry
            Hostname of Docker container registry.
        repository
            Repository of images (for example, ``lsstsqre/sciplat-lab``).

        Returns
        -------
        list of str
            All the tags found for that repository.
        """
        url = f"https://{registry}/v2/{repository}/tags/list"
        r = await self._client.get(url, headers=self._build_headers(registry))
        if r.status_code == 401:
            headers = await self._authenticate(registry, r)
            r = await self._client.get(url, headers=headers)
        try:
            r.raise_for_status()
            return r.json()["tags"]
        except Exception as e:
            msg = f"Error listing tags from <{url}>"
            raise DockerRegistryError(msg) from e

    async def get_image_digest(
        self, registry: str, repository: str, tag: str
    ) -> str:
        """Get the digest associated with an image tag.

        Parameters
        ----------
        registry
            Hostname of Docker container registry.
        repository
            Repository of images (for example, ``lsstsqre/sciplat-lab``).
        tag
            The tag to inspect.

        Returns
        -------
        str
            The digest, such as ``sha256:abcdef``.
        """
        url = f"https://{registry}/v2/{repository}/manifests/{tag}"
        r = await self._client.head(url, headers=self._build_headers(registry))
        if r.status_code == 401:
            headers = await self._authenticate(registry, r)
            r = await self._client.head(url, headers=headers)
        try:
            r.raise_for_status()
            return r.headers["Docker-Content-Digest"]
        except Exception as e:
            msg = f"Error retrieving digest from <{url}>"
            raise DockerRegistryError(msg) from e

    async def _authenticate(
        self, host: str, response: Response
    ) -> dict[str, str]:
        """Authenticate after getting an auth challenge.

        Sets headers to use for subsequent requests.  The caller should then
        retry the request.

        Parameters
        ----------
        host
            The host to which we're making the request, and the key to find
            Docker credentials to use for authentication.
        response
            The response from the server that includes an auth challenge.

        Returns
        -------
        dict of str to str
            New headers to use for this host.

        Raises
        ------
        DockerRegistryError
            Some failure in talking to the Docker registry API server.
        """
        if host in self._authorization:
            msg = f"Authentication credentials for {host} rejected"
            raise DockerRegistryError(msg)

        credentials = self._credentials.get(host)
        if not credentials:
            msg = f"No Docker API credentials available for {host}"
            raise DockerRegistryError(msg)

        challenge = response.headers.get("WWW-Authenticate")
        if not challenge:
            msg = f"Docker API 401 response from {host} contains no challenge"
            raise DockerRegistryError(msg)
        challenge_type, params = challenge.split(None, 1)
        challenge_type = challenge_type.lower()

        if challenge_type == "basic":
            self._authorization[host] = credentials.authorization
            self._logger.info(
                "Authenticated to Docker API with basic auth",
                registry=host,
                username=credentials.username,
            )
        elif challenge_type == "bearer":
            # Bearer is used by Docker's official registry.
            token = await self._get_bearer_token(host, credentials, params)
            self._authorization[host] = f"Bearer {token}"
            self._logger.info(
                "Authenticated to Docker API with bearer token",
                registry=host,
                username=credentials.username,
            )
        else:
            msg = f"Unknown authentication challenge type {challenge_type}"
            raise DockerRegistryError(msg)

        return self._build_headers(host)

    def _build_headers(self, host: str) -> dict[str, str]:
        """Construct the headers used for a query to a given host.

        Adds the ``Authorization`` header if we have discovered that this host
        requires authentication.

        Parameters
        ----------
        host
            Docker registry API host.

        Returns
        -------
        dict of str to str
            Headers to pass to this host.
        """
        headers = {
            "Accept": "application/vnd.docker.distribution.manifest.v2+json"
        }
        if host in self._authorization:
            headers["Authorization"] = self._authorization[host]
        return headers

    async def _get_bearer_token(
        self, host: str, credentials: DockerCredentials, challenge_params: str
    ) -> str:
        """Get a bearer token for subsequent API calls.

        Parameters
        ----------
        host
            The host to which we're authenticating.
        credentials
            Authentication credentials.
        challenge_params
            The parameters it sent in the ``WWW-Authenticate`` header.

        Returns
        -------
        str
            The bearer token to use for subsequent calls to that host.

        Raises
        ------
        DockerRegistryError
            Some failure in talking to the Docker registry API server.
        """
        # We need to reflect the challenge parameters back as query
        # parameters when obtaining our bearer token.
        self._logger.debug(
            "Parsing Docker API bearer challenge", params=challenge_params
        )
        params = {}
        for param in challenge_params.split(","):
            key, value = param.split("=", 1)
            params[key] = value.replace('"', "")

        # This is hugely unsafe and needs some sort of sanity check.
        url = params["realm"]

        # Request a bearer token.
        self._logger.info(
            "Obtaining Docker API bearer token",
            registry=host,
            username=credentials.username,
        )
        auth = (credentials.username, credentials.password)
        r = await self._client.get(url, auth=auth, params=params)
        try:
            r.raise_for_status()
            return r.json()["token"]
        except Exception as e:
            msg = f"Error getting bearer token from <{url}>"
            raise DockerRegistryError(msg) from e
