"""Image manager implementation for the Docker API."""

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import override

from structlog.stdlib import BoundLogger

from ...models.images import (
    DockerSource,
    ImageFilterPolicy,
    RSPImageTagCollection,
)
from ...storage.docker import DockerStorageClient
from ._base import ImagesManager

__all__ = ["DockerImagesManager"]


class DockerImagesManager(ImagesManager[DockerSource]):
    """Manage Nublado images using the Docker API.

    Parameters
    ----------
    docker_client
        Docker client.
    logger
        Logger to use.
    """

    def __init__(
        self, docker_client: DockerStorageClient, logger: BoundLogger
    ) -> None:
        self._client = docker_client
        self._logger = logger

    @override
    async def delete_tags(
        self, config: DockerSource, tags: Iterable[str]
    ) -> None:
        for tag in tags:
            digest = await self._client.get_image_digest(config, tag)
            await self._client.delete_image(config, digest)

    @override
    async def list_tags(self, config: DockerSource) -> set[str]:
        return await self._client.list_tags(config)

    @override
    async def prune_images(
        self,
        config: DockerSource,
        policy: ImageFilterPolicy,
        *,
        dry_run: bool = True,
    ) -> list[str]:
        all_tags = await self._client.list_tags(config)
        collection = RSPImageTagCollection.from_tag_names(all_tags)
        to_delete = collection.filter(
            policy,
            datetime.now(tz=UTC),
            invert=True,
            remove_arch_specific=False,
        )

        # Do the deletion if desired, and build the list of images that would
        # be deleted by tag. Deletion has to be done by digest, so we have to
        # retrieve the digest for each tag. Do this one image at a time, since
        # deletions don't have to be fast and that reduces the chance of being
        # rate-limited.
        #
        # Some tags may be aliases, so to avoid deleting the same digest
        # twice, keep a record of the ones that have already been processed.
        tags = [t.tag for t in to_delete]
        deleted = set()
        if not dry_run:
            for tag in tags:
                digest = await self._client.get_image_digest(config, tag)
                if digest in deleted:
                    continue
                await self._client.delete_image(config, digest)
                deleted.add(digest)

        # Return the tags that were or would have been deleted.
        return tags
