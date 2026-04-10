"""Client for the Docker v2 API."""

import json
from pathlib import Path
from typing import Self
from urllib.parse import urljoin

from httpx import AsyncClient, HTTPError, Response
from safir.http import PaginationLinkData
from structlog.stdlib import BoundLogger

from ..exceptions import DockerError, DockerInvalidUrlError
from ..models.domain.docker import DockerCredentials
from ..models.v1.prepuller import DockerSourceOptions

_MANIFEST_ACCEPT_TYPES = [
    "application/vnd.docker.distribution.manifest.v2+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.oci.image.index.v1+json",
    "application/json;q=0.5",
]
"""Possible MIME types for an image manifest for the ``Accept`` header."""

__all__ = [
    "DockerCredentialStore",
    "DockerStorageClient",
]


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
            credentials[host] = DockerCredentials.from_config(config)
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
        DockerCredentials or None
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

    def set(self, host: str, credentials: DockerCredentials) -> None:
        """Set credentials for a given host.

        Parameters
        ----------
        host
            The Docker API host.
        credentials
            The credentials to use for that host.
        """
        self._credentials[host] = credentials

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
    credentials_path
        Path to a Docker credentials store.
    http_client
        Client to use to make requests.
    logger
        Logger for log messages.
    """

    def __init__(
        self,
        *,
        credentials_path: Path,
        http_client: AsyncClient,
        logger: BoundLogger,
    ) -> None:
        self._credentials = DockerCredentialStore.from_path(credentials_path)
        self._client = http_client
        self._logger = logger

        # Cached authorization headers by registry. This is populated once we
        # have had to authenticate to a registry and may contain the HTTP
        # Basic string or may contain a bearer token that we previously
        # obtained via API calls.
        self._authorization: dict[str, str] = {}

    async def get_image_digest(
        self, config: DockerSourceOptions, tag: str
    ) -> str:
        """Get the digest associated with an image tag.

        Parameters
        ----------
        config
            Configuration for the registry and repository to use.
        tag
            The tag to inspect.

        Returns
        -------
        str
            The digest, such as ``sha256:abcdef``.

        Raises
        ------
        DockerError
            Unable to retrieve the digest from the Docker Registry.
        """
        url = (
            f"https://{config.registry}/v2/{config.repository}/manifests/{tag}"
        )
        headers = self._build_headers(config.registry, manifest=True)
        try:
            r = await self._client.head(url, headers=headers)
            if r.status_code == 401:
                headers = await self._authenticate(config.registry, r)
                r = await self._client.head(url, headers=headers)
            r.raise_for_status()
            digest = r.headers["Docker-Content-Digest"]
        except HTTPError as e:
            raise DockerError.from_exception(e) from e
        except Exception as e:
            error = f"{type(e).__name__}: {e!s}"
            msg = f"Cannot get image digest from Docker registry: {error}"
            raise DockerError(msg, method="GET", url=url) from e
        else:
            self._logger.debug(
                "Retrieved image digest for tag",
                registry=config.registry,
                repository=config.repository,
                tag=tag,
                digest=digest,
            )
            return digest

    async def list_tags(self, config: DockerSourceOptions) -> set[str]:
        """List tags for a given registry and repository.

        Parameters
        ----------
        config
            Configuration for the registry and repository to use.

        Returns
        -------
        set of str
            All the non-platform-specific tags found for that repository.
        """
        headers = self._build_headers(config.registry)
        all_tags = set()
        seen_urls = set()
        logger = self._logger.bind(
            registry=config.registry, repository=config.repository
        )

        # We're assuming HTTPS.  If you have an HTTP-only registry without
        # TLS in 2025, well, I feel bad for you, son.  You got 99 problems
        # and your URL's just one.
        url = f"https://{config.registry}/v2/{config.repository}/tags/list"

        # The results may be paginated, so keep retrieving pages for as long
        # as each page has a Link header with a next element.
        while True:
            seen_urls.add(url)
            try:
                r = await self._client.get(url, headers=headers)
                if r.status_code == 401:
                    headers = await self._authenticate(config.registry, r)
                    r = await self._client.get(url, headers=headers)
                r.raise_for_status()
                tags = r.json()["tags"]
            except HTTPError as e:
                raise DockerError.from_exception(e) from e
            except Exception as e:
                error = f"{type(e).__name__}: {e!s}"
                msg = f"Cannot parse response from Docker registry: {error}"
                raise DockerError(msg, method="GET", url=url) from e

            # Add the seen tags to the set.
            logger.debug(f"Retrieved {len(tags)} image tags")
            all_tags.update(tags)

            # Check for a continuation.
            if next_url := self._parse_next_link_header(config, r, url):
                if next_url in seen_urls:
                    raise DockerInvalidUrlError(
                        "Repeated tag page URL", url, next_url, method="GET"
                    )
                url = next_url
                logger.debug("Following Link header", url=url)
            else:
                break

        # All done, return the results.
        logger.debug("Listed all tags", count=len(all_tags))
        return all_tags

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
        DockerError
            Some failure in talking to the Docker registry API server.
        """
        if host in self._authorization:
            msg = f"Authentication credentials for {host} rejected"
            raise DockerError(msg)

        credentials = self._credentials.get(host)
        if not credentials:
            msg = f"No Docker API credentials available for {host}"
            raise DockerError(msg)

        challenge = response.headers.get("WWW-Authenticate")
        if not challenge:
            msg = f"Docker API 401 response from {host} contains no challenge"
            raise DockerError(msg)
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
            msg = f'Unknown Docker authentication challenge "{challenge_type}"'
            raise DockerError(msg)

        return self._build_headers(host)

    def _build_headers(
        self, host: str, *, manifest: bool = False
    ) -> dict[str, str]:
        """Construct the headers used for a query to a given host.

        Adds the ``Authorization`` header if we have discovered that this host
        requires authentication.

        Parameters
        ----------
        host
            Docker registry API host.
        manifest
            Whether to construct the headers for retrieving a manifest.

        Returns
        -------
        dict of str to str
            Headers to pass to this host.
        """
        if manifest:
            headers = {"Accept": ", ".join(_MANIFEST_ACCEPT_TYPES)}
        else:
            headers = {"Accept": "application/json"}
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
        DockerError
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
            url=url,
            username=credentials.username,
        )
        auth = (credentials.username, credentials.password)
        try:
            r = await self._client.get(url, auth=auth, params=params)
            r.raise_for_status()
            return r.json()["token"]
        except HTTPError as e:
            raise DockerError.from_exception(e) from e
        except Exception as e:
            error = f"{type(e).__name__}: {e!s}"
            msg = f"Cannot parse Docker registry login response: {error}"
            raise DockerError(msg, method="GET", url=url) from e

    def _parse_next_link_header(
        self, config: DockerSourceOptions, response: Response, base_url: str
    ) -> str | None:
        """Parse the response for a ``Link`` header with a next URL.

        Parameters
        ----------
        config
            Configuration for the registry and repository to use.
        response
            HTTP response, which may contain a ``Link`` header.
        base_url
            URL retrieved to create that response, used for relative link
            following.

        Raises
        ------
        DockerInvalidUrlError
            Raised if the next URL is not relative to the expected registry.
        """
        link = response.headers.get("Link")
        if not link:
            return None
        link_data = PaginationLinkData.from_header(link)
        if link_data.next_url:
            next_url = urljoin(base_url, link_data.next_url)
            if not next_url.startswith(f"https://{config.registry}/"):
                raise DockerInvalidUrlError(
                    f"Docker Link URL not relative to {config.registry}",
                    base_url,
                    next_url,
                    method="GET",
                )
            return next_url
        else:
            return None
