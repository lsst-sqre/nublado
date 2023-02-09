"""Docker v2 registry client, based on cachemachine's client."""
import asyncio
from typing import List, Optional, cast

from httpx import AsyncClient, Response
from structlog.stdlib import BoundLogger

from ..exceptions import DockerRegistryError
from ..models.domain.docker import DockerCredentials
from ..models.tag import RSPTag, RSPTagList, TagMap
from ..util import extract_untagged_path_from_image_ref


class DockerStorageClient:
    """Simple client for querying Docker registry."""

    def __init__(
        self,
        logger: BoundLogger,
        host: str,
        repository: str,
        recommended_tag: str,
        http_client: AsyncClient,
        credentials: Optional[DockerCredentials] = None,
    ) -> None:
        """Create a new Docker Client.

        Parameters
        ----------
        """
        self.host = host
        self.repository = repository
        self.http_client = http_client
        self.logger = logger
        self.headers = {
            "Accept": "application/vnd.docker.distribution.manifest.v2+json"
        }
        self.credentials = credentials
        self.recommended_tag = recommended_tag

    @property
    def ref(self) -> str:
        return f"{self.host}{self.repository}"

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
        if r.status_code == 200:
            body = r.json()
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

        Get the digest associated with an image tag.

        Parameters
        ----------
        tag: the tag to inspect
        authenticate: should we to authenticate?  Used internally for
          retrying after successful authentication.

        Returns the digest as a string, such as "sha256:abcdef"
        """
        url = f"https://{self.host}/v2/{self.repository}/manifests/{tag}"
        r = await self.http_client.head(url, headers=self.headers)
        if r.status_code == 200:
            return r.headers["Docker-Content-Digest"]
        elif r.status_code == 401 and authenticate:
            await self._authenticate(r)
            return await self.get_image_digest(tag, authenticate=False)
        else:
            msg = f"Unknown error retrieving digest from <{url}>: {r}"
            raise DockerRegistryError(msg)

    async def _authenticate(self, response: Response) -> None:
        """Internal method to authenticate after getting an auth challenge.

        Doesn't return anything but will set additional headers for future
        requests.

        Parameters
        ----------
        response: response that contains an auth challenge.
        """
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
            self.headers["Authorization"] = self.credentials.authorization
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
            auth = (self.credentials.username, self.credentials.password)

            self.logger.info(
                f"Obtaining bearer token for {self.credentials.username}"
            )
            r = await self.http_client.get(url, auth=auth, params=parts)
            if r.status_code == 200:
                body = r.json()
                token = body["token"]
                self.headers["Authorization"] = f"Bearer {token}"
                self.logger.info("Authenticated with bearer token")
            else:
                msg = f"Error getting token from <{url}>: {r}"
                raise DockerRegistryError(msg)
        else:
            msg = f"Unknown authentication challenge {challenge}"
            raise DockerRegistryError(msg)

    async def get_tag_map(self) -> TagMap:
        """This is the only actual repository function we directly perform
        (since pulls are done by K8s).  We query all the tags for a given
        repository to get their digests, inflate the tag and digest pairs
        into RSPTag objects, and return a structure with dicts indexed by
        tag and by digest.  This in turn will let us easily compare what
        we have remotely and what we have locally, because it doesn't matter
        what tag we pulled a given image by, but whether we have an image
        with the proper digest already on a given node.
        """
        tags = await self.list_tags()
        tasks: List[asyncio.Task] = list()
        for tag in tags:
            # We probably want to rate-limit this ourselves somehow
            tasks.append(asyncio.create_task(self.get_image_digest(tag)))
        digests = cast(
            List[str], await asyncio.gather(*tasks)
        )  # gather doesn't know it's all strings, but we do.
        t_to_d = dict(zip(tags, digests))
        rsp_tags: List[RSPTag] = list()
        # Inflate each tag/digest pair into an RSPTag
        untagged_ref = extract_untagged_path_from_image_ref(self.ref)
        for tag in t_to_d:
            alias_tags = []
            if tag == self.recommended_tag:
                alias_tags = [self.recommended_tag]
            rsp_tags.append(
                RSPTag.from_tag(
                    tag=tag,
                    digest=t_to_d[tag],
                    image_ref=f"{untagged_ref}:{tag}",
                    alias_tags=alias_tags,
                )
            )
        # Put it into a RSPTagList, which will sort the tags and produce
        # the map.
        rsp_taglist = RSPTagList(tags=rsp_tags)
        return rsp_taglist.tag_map
