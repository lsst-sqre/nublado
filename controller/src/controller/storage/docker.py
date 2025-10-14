"""Client for the Docker v2 API."""

import json
import re
from pathlib import Path
from typing import Self
from urllib.parse import urlparse

from httpx import AsyncClient, HTTPError, Response
from structlog.stdlib import BoundLogger

from ..exceptions import DockerRegistryError
from ..models.domain.arch_filter import filter_arch_tags
from ..models.domain.docker import DockerCredentials
from ..models.v1.prepuller import DockerSourceOptions

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

    async def list_tags(self, config: DockerSourceOptions) -> list[str]:
        """List tags for a given registry and repository.

        This is not comprehensive, because we filter out platform-specific
        tags that have matching base tags.

        Parameters
        ----------
        config
            Configuration for the registry and repository to use.

        Returns
        -------
        list of str
            All the non-platform-specific tags found for that repository.
        """
        # We're assuming HTTPS.  If you have an HTTP-only registry without
        # TLS in 2025, well, I feel bad for you, son.  You got 99 problems
        # and your URL's just one.
        url = f"https://{config.registry}/v2/{config.repository}/tags/list"
        headers = self._build_headers(config.registry)
        all_filtered_tags: set[str] = set()
        while True:
            try:
                r = await self._client.get(url, headers=headers)
                if r.status_code == 401:
                    headers = await self._authenticate(config.registry, r)
                    r = await self._client.get(url, headers=headers)
                r.raise_for_status()
                tags = r.json()["tags"]
            except HTTPError as e:
                raise DockerRegistryError.from_exception(e) from e
            except Exception as e:
                error = f"{type(e).__name__}: {e!s}"
                msg = f"Cannot parse response from Docker registry: {error}"
                raise DockerRegistryError(msg, method="GET", url=url) from e
            else:
                filtered = filter_arch_tags(tags)
                count = len(filtered)
                self._logger.debug(
                    f"Listed {count} image tags",
                    registry=config.registry,
                    repository=config.repository,
                    count=count,
                )
                current_tags = set(filtered)
                duplicates = current_tags.intersection(all_filtered_tags)
                if duplicates:
                    tag_word = "tag" if len(duplicates) == 1 else "tags"
                    self._logger.error(
                        f"Duplicate {tag_word}: {duplicates}"
                        f" Bailing out of tag-reading loop"
                    )
                    all_filtered_tags.update(
                        current_tags.difference(duplicates)
                    )
                    break
                all_filtered_tags.update(current_tags)
            link = r.headers.get("Link")
            if not link:
                # Normal loop exit: we have no links to follow.
                break
            link_url = self._parse_next_link_header(link)
            if not link_url:
                # Normal loop exit: we have no "next" link to follow.
                break
            url = self._get_next_url(link_url, config)
        return list(all_filtered_tags)

    @staticmethod
    def _get_next_url(link_url: str, config: DockerSourceOptions) -> str:
        parsed = urlparse(link_url)
        if parsed.netloc:
            # It specified a netloc, so use it as is.
            return link_url
        # Relative to the current netloc (this is how GHCR does it).
        if link_url[0] != "/":
            link_url = f"/{link_url}"
        return f"https://{config.registry}{link_url}"

    @staticmethod
    def _parse_next_link_header(link: str) -> str | None:
        # If there's a rel="next" link, return the URL it points to.
        # Otherwise, return None.
        # Borrowed from safir.database._pagination.PaginationLinkData
        link_re = re.compile(
            r'\s*<(?P<target>[^>]+)>;\s*rel="(?P<type>[^"]+)"'
        )
        mat = re.match(link_re, link)
        if not mat:
            return None
        if mat.group("type") != "next":
            return None
        return mat.group("target")

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
        DockerRegistryError
            Unable to retrieve the digest from the Docker Registry.
        """
        url = (
            f"https://{config.registry}/v2/{config.repository}/manifests/{tag}"
        )
        headers = self._build_manifest_headers(config.registry)
        try:
            r = await self._client.head(url, headers=headers)
            if r.status_code == 401:
                headers = await self._authenticate(config.registry, r)
                r = await self._client.head(url, headers=headers)
            r.raise_for_status()
            digest = r.headers["Docker-Content-Digest"]
        except HTTPError as e:
            raise DockerRegistryError.from_exception(e) from e
        except Exception as e:
            error = f"{type(e).__name__}: {e!s}"
            msg = f"Cannot get image digest from Docker registry: {error}"
            raise DockerRegistryError(msg, method="GET", url=url) from e
        else:
            self._logger.debug(
                "Retrieved image digest for tag",
                registry=config.registry,
                repository=config.repository,
                tag=tag,
                digest=digest,
            )
            return digest

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
            msg = f'Unknown Docker authentication challenge "{challenge_type}"'
            raise DockerRegistryError(msg)

        return self._build_headers(host)

    def _build_manifest_headers(self, host: str) -> dict[str, str]:
        """Construct the headers we need for a query to a given host to
        inspect a manifest. This requires additional media types.
        """
        headers = self._build_headers(host)
        headers["Accept"] = (
            "application/vnd.docker.distribution.manifest.v2+json, "
            "application/vnd.docker.distribution.manifest.list.v2+json, "
            "application/vnd.oci.image.manifest.v1+json, "
            "application/vnd.oci.image.index.v1+json, "
            "application/json;q=0.5"
        )
        return headers

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
            url=url,
            username=credentials.username,
        )
        auth = (credentials.username, credentials.password)
        try:
            r = await self._client.get(url, auth=auth, params=params)
            r.raise_for_status()
            return r.json()["token"]
        except HTTPError as e:
            raise DockerRegistryError.from_exception(e) from e
        except Exception as e:
            error = f"{type(e).__name__}: {e!s}"
            msg = f"Cannot parse Docker registry login response: {error}"
            raise DockerRegistryError(msg, method="GET", url=url) from e
