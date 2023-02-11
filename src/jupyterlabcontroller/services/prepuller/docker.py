"""Docker client for image prepuller."""

import asyncio

from structlog.stdlib import BoundLogger

from ...models.tag import RSPTag, RSPTagList, TagMap
from ...models.v1.prepuller_config import PrepullerConfiguration
from ...storage.docker import DockerStorageClient
from .state import PrepullerState


class PrepullerDockerClient:
    """Query Docker for available images.

    Fetches tag information for a given repository from a Docker registry.
    These are known as our remote images and are used to calculate which
    images to prepull.
    """

    def __init__(
        self,
        namespace: str,
        state: PrepullerState,
        docker_client: DockerStorageClient,
        config: PrepullerConfiguration,
        logger: BoundLogger,
    ) -> None:
        self.logger = logger
        self.state = state
        self.namespace = namespace
        self.docker_client = docker_client
        self.config = config

    async def get_tag_map(self) -> TagMap:
        """Get a list of all available tags.

        Query all the tags for a given repository to get their digests,
        inflate the tag and digest pairs into RSPTag objects, and return a
        structure with dicts indexed by tag and by digest.  This in turn will
        let us easily compare what we have remotely and what we have locally,
        because it doesn't matter what tag we pulled a given image by, but
        whether we have an image with the proper digest already on a given
        node.
        """
        # Get all the tags and digests from the Docker API.  This is much too
        # aggressive in parallelism and also is doing too much work since we
        # don't care about the digests for most tags.
        tags = await self.docker_client.list_tags(
            self.config.registry, self.config.repository
        )
        tasks = [
            asyncio.create_task(
                self.docker_client.get_image_digest(
                    self.config.registry, self.config.repository, tag
                )
            )
            for tag in tags
        ]
        digests = await asyncio.gather(*tasks)
        digest_for_tag = dict(zip(tags, digests))

        # Inflate each tag/digest pair into an RSPTag
        rsp_tags = []
        for tag, digest in digest_for_tag.items():
            alias_tags = []
            if tag == self.config.recommended_tag:
                alias_tags = [self.config.recommended_tag]
            rsp_tags.append(
                RSPTag.from_tag(
                    tag=tag,
                    digest=digest,
                    image_ref=f"{self.config.path}:{tag}",
                    alias_tags=alias_tags,
                )
            )

        # Put it into a RSPTagList, which will sort the tags and produce
        # the map.
        return RSPTagList(tags=rsp_tags).tag_map

    async def refresh_if_needed(self) -> None:
        if self.state.needs_docker_refresh:
            await self.refresh_state_from_docker_repo()

    async def refresh_state_from_docker_repo(self) -> None:
        self.logger.info("Querying docker repository for image tags.")
        tag_map = await self.get_tag_map()
        self.state.set_remote_images(tag_map)
        self.state.update_docker_check_time()
        self.logger.info("Docker repository query complete.")
