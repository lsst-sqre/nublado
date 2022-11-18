"""Docker v2 registry client, based on cachemachine's client."""
import asyncio
import base64
import json
from os.path import dirname
from typing import Any, Dict, List, Optional

from httpx import AsyncClient, Response
from structlog.stdlib import BoundLogger

from ..config import Configuration
from ..constants import CONFIGURATION_PATH, DOCKER_SECRETS_PATH
from ..models.domain.docker import DockerCredentials as DC
from ..models.domain.prepuller import TagMap
from ..models.exceptions import DockerRegistryError
from ..models.v1.prepuller_config import PrepullerConfiguration


class DockerStorageClient:
    """Simple client for querying Docker registry."""

    secrets_path: Optional[str] = None
    credentials: Optional[DC] = None
    host: Optional[str] = None
    repository: Optional[str] = None

    def __init__(
        self,
        logger: BoundLogger,
        config: Configuration,
        http_client: AsyncClient,
    ) -> None:
        """Create a new Docker Client.

        Parameters
        ----------
        """
        prepuller_config: PrepullerConfiguration = config.images
        self.host = prepuller_config.registry
        self.repository = prepuller_config.path
        secrets_path: str = DOCKER_SECRETS_PATH
        if config.runtime.path != CONFIGURATION_PATH:
            # We are loading the config from non-container-provided place,
            # so therefore the secrets will reside in the same directory
            # as docker_config.json (by convention).
            secrets_path = (
                f"{dirname(str(config.runtime.path))}/docker_config.json"
            )
        self.secrets_path = secrets_path
        self.http_client = http_client
        self.logger = logger
        self.headers = {
            "Accept": "application/vnd.docker.distribution.manifest.v2+json"
        }
        self._lookup_credentials()

    async def list_tags(self, authenticate: bool = True) -> List[str]:
        """List all the tags.

        Lists all the tags for the repository this client is used with.

        Parameters
        ----------
        authenticate: should we try and authenticate?  Used internally
          for retrying after successful authentication.
        """
        url = f"https://{self.host}/v2/{self.repository}/tags/list"
        r = await self.http_client.get(url, headers=self.headers)
        self.logger.debug(f"List tags response: {r}")
        if r.status_code == 200:
            body = await r.json()
            self.logger.debug(body)
            return body["tags"]
        elif r.status_code == 401 and authenticate:
            await self._authenticate(r)
            return await self.list_tags(authenticate=False)
        else:
            msg = f"Unknown error listing tags from <{url}>: {r}"
            raise DockerRegistryError(msg)

    async def get_image_digest(
        self, tag: str, authenticate: bool = True
    ) -> str:
        """Get the digest of a tag.

        Get the associated image digest of a Docker tag.

        Parameters
        ----------
        tag: the tag to inspect
        authenticate: should we try and authenticate?  Used internally
          for retrying after successful authentication.

        Returns the digest as a string, such as "sha256:abcdef"
        """
        url = f"https://{self.host}/v2/{self.repository}/manifests/{tag}"
        r = await self.http_client.head(url, headers=self.headers)
        self.logger.debug(f"Get image digest response: {r}")
        if r.status_code == 200:
            return r.headers["Docker-Content-Digest"]
        elif r.status_code == 401 and authenticate:
            await self._authenticate(r)
            return await self.get_image_digest(tag, authenticate=False)
        else:
            msg = f"Unknown error retrieving digest from <{url}>: {r}"
            raise DockerRegistryError(msg)

    async def get_tag_map(self) -> TagMap:
        tags = await self.list_tags()
        tasks: List[asyncio.Task] = list()
        for tag in tags:
            tasks.append(asyncio.create_task(self.get_image_digest(tag)))
        digests: List[Any] = await asyncio.gather(*tasks)  # Actually str...
        d_str: List[str] = [str(x) for x in digests]  # Really a no-op
        t_to_d: Dict[str, str] = dict(zip(tags, d_str))
        d_to_t: Dict[str, List[str]] = dict()
        for tag in t_to_d:
            digest = t_to_d[tag]
            if digest not in d_to_t:
                d_to_t[digest] = list()
            d_to_t[digest].append(tag)
        return TagMap(by_digest=d_to_t, by_tag=t_to_d)

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

        if self.credentials is None:
            raise DockerRegistryError(
                "Cannot authenticate with no credentials"
            )

        if challenge_type == "basic":
            # Basic auth is used by the Nexus Docker Registry.
            self.headers[
                "Authorization"
            ] = f"Basic {self.credentials.base64_auth}"
            self.logger.info(
                f"Authenticated with basic auth as {self.credentials.username}"
            )
        elif challenge_type == "bearer":
            # Bearer is used by Docker's official registry.
            self.logger.debug(f"Parsing challenge params {params}")
            parts = dict()
            for p in params.split(","):
                (k, v) = p.split("=")
                parts[k] = v.replace('"', "")

            url = parts["realm"]
            auth = None

            if self.credentials.username and self.credentials.password:
                auth = (self.credentials.username, self.credentials.password)

            self.logger.info(
                f"Obtaining bearer token for {self.credentials.username}"
            )
            r = await self.http_client.get(url, auth=auth, params=parts)
            if r.status_code == 200:
                body = await r.json()
                token = body["token"]
                self.headers["Authorization"] = f"Bearer {token}"
                self.logger.info("Authenticated with bearer token")
            else:
                msg = f"Error getting token from <{url}>: {r}"
                raise DockerRegistryError(msg)
        else:
            msg = f"Unknown authentication challenge {challenge}"
            raise DockerRegistryError(msg)

    def _lookup_credentials(self) -> None:
        """Find credentials for the current client.

        Using the repository host, look for an entry in the dockerconfig
        whose key is a string with which the hostname ends, which contains
        a username and password for authenticating.
        """

        if self.secrets_path is None:
            self.logger.warning("Cannot determine secrets location")
            return
        try:
            with open(self.secrets_path) as f:
                self.logger.debug(f"Parsing {self.secrets_path}")
                credstore = json.loads(f.read())
                if self.host is None:
                    # This can't happen but mypy doesn't know that
                    self.logger.warning("Could not determine host from config")
                    return
                for host in credstore["auths"]:
                    if not host:
                        self.logger.warning(
                            "host is empty; setting default credentials"
                        )
                        host = ""
                    b64auth = credstore["auths"][host]["auth"]
                    basic_auth = base64.b64decode(b64auth).decode()
                    username, password = basic_auth.split(":", 1)
                    if self.host.endswith(host):
                        self.credentials = DC(
                            registry_host=host,
                            username=username,
                            password=password,
                            base64_auth=b64auth,
                        )
                    self.logger.debug(f"Added authentication for '{host}'")
        except FileNotFoundError:
            # It's possible we're only using unauthenticated registries.
            self.logger.warning(
                f"no Docker config found at {self.secrets_path}"
            )
        if self.credentials is None:
            self.logger.warning(
                f"No Docker credentials loaded for {self.host}"
            )
