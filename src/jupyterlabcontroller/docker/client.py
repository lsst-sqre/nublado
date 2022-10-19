"""Client for accessing Docker v2 registry using httpx.  We're going to
use the supplied http_client_dependency, and a credential cache stored in the
runtime container as pull-secrets."""

import base64
from typing import Dict, List, Optional, Tuple

from fastapi import Depends
from httpx import AsyncClient, BasicAuth, Response
from models.docker import DockerCredentials, DockerRegistryError
from safir.dependencies.http_client import http_client_dependency
from safir.dependencies.logger import logger_dependency
from structlog.stdlib import BoundLogger

from ..runtime.docker import docker_credentials


class DockerClient:
    """Simple client for querying Docker registry."""

    def __init__(
        self,
        host: str,
        repository: str,
        client: AsyncClient = Depends(http_client_dependency),
        logger: BoundLogger = Depends(logger_dependency),
    ) -> None:
        """Create a new Docker Client.

        Parameters
        ----------
        host: host to contact for registry.
        repository: name of the docker repository to query,
          e.g. lsstsqre/sciplat-lab
        """
        key = (host, repository)
        cached_client: Optional[DockerClient] = _clientcache.get(key)
        if cached_client is not None:
            self = cached_client
            return
        self.host = host
        self.repository = repository
        self.headers = {
            "Accept": "application/vnd.docker.distribution.manifest.v2+json"
        }
        self.auth: Optional[DockerCredentials] = docker_credentials.get(host)
        self.client = client
        self.logger = logger
        _clientcache[key] = self

    async def list_tags(self, authenticate: bool = True) -> List[str]:
        """List all the tags.

        Lists all the tags for the repository this client is used with.

        Parameters
        ----------
        authenticate: should we try and authenticate?  Used internally
          for retrying after successful authentication.
        """
        url = f"https://{self.host}/v2/{self.repository}/tags/list"
        r = await self.client.get(url, headers=self.headers)
        if r.status_code == 200:
            body = await r.json()
            return body["tags"]
        elif r.status_code == 401 and authenticate:
            await self._authenticate(r)
            return await self.list_tags(authenticate=False)
        else:
            msg = f"Unknown error listing tags from <{url}>: {r}"
            raise DockerRegistryError(msg)

    async def get_image_hash(self, tag: str, authenticate: bool = True) -> str:
        """Get the hash of a tag.

        Get the associated image hash of a Docker tag.

        Parameters
        ----------
        tag: the tag to inspect
        authenticate: should we try and authenticate?  Used internally
          for retrying after successful authentication.

        Returns the hash as a string, such as "sha256:abcdef"
        """
        url = f"https://{self.host}/v2/{self.repository}/manifests/{tag}"
        r = await self.client.head(url, headers=self.headers)
        self.logger.debug(f"Get image hash response: {r}")
        if r.status_code == 200:
            return r.headers["Docker-Content-Digest"]
        elif r.status_code == 401 and authenticate:
            await self._authenticate(r)
            return await self.get_image_hash(tag, authenticate=False)
        else:
            msg = f"Unknown error retrieving hash from <{url}>: {r}"
            raise DockerRegistryError(msg)

    async def _authenticate(self, response: Response) -> None:
        """Internal method to authenticate after getting an auth challenge.

        Doesn't return anything but will set additional headers for future
        requests.

        Parameters
        ----------
        response: response that contains an auth challenge.
        """
        self.logger.debug(f"Authenticating {response}")
        challenge = response.headers.get("WWW-Authenticate")
        if not challenge:
            raise DockerRegistryError("No authentication challenge")

        (challenge_type, params) = challenge.split(" ", 1)
        challenge_type = challenge_type.lower()

        if challenge_type == "basic":
            # Basic auth is used by the Nexus Docker Registry.
            if not self.auth:
                msg = f"No auth info for {self.host}"
                raise DockerRegistryError(msg)
            authb64 = base64.b64encode(
                bytes(f"{self.auth.username}:{self.auth.password}", "utf-8")
            )
            self.headers["Authorization"] = str(authb64)
            self.logger.info(
                f"Authenticated to {self.host} with basic auth "
                + f"as {self.auth.username}"
            )
        elif challenge_type == "bearer":
            # Bearer is used by Docker's official registry.
            self.logger.debug(f"Parsing challenge params {params}")
            parts = {}
            for p in params.split(","):
                (k, v) = p.split("=")
                parts[k] = v.replace('"', "")

            url = parts["realm"]
            auth = None

            if self.auth:
                auth = BasicAuth(
                    self.auth.username, password=self.auth.password
                )

            self.logger.info(
                f"Obtaining bearer token for {self.auth.username}"
            )
            r = await self.client.get(url, auth=auth, params=parts)
            if r.status_code == 200:
                body = await r.json()
                token = body["token"]
                self.headers["Authorization"] = f"Bearer {token}"
                self.logger.info(
                    f"Authenticated to {self.host} with " + "bearer token"
                )
            else:
                msg = f"Error getting token from <{url}>: {r}"
                raise DockerRegistryError(msg)
        else:
            msg = f"Unknown authentication challenge {challenge}"
            raise DockerRegistryError(msg)


_clientcache: Dict[Tuple[str, str], DockerClient] = {}
