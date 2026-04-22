"""Image manager implementation for the Google Artifact Registry API."""

from datetime import UTC, datetime
from typing import override

from structlog.stdlib import BoundLogger

from ...models.images import GARSource, ImageFilterPolicy
from ...storage.gar import GARStorageClient
from ._base import ImagesManager

__all__ = ["GARImagesManager"]


class GARImagesManager(ImagesManager[GARSource]):
    """Manage Nublado images using the Google Artifact Registry API.

    Parameters
    ----------
    gar_client
        Google Artifact Registry client.
    logger
        Logger to use.
    """

    def __init__(
        self, gar_client: GARStorageClient, logger: BoundLogger
    ) -> None:
        self._client = gar_client
        self._logger = logger

    @override
    async def list_tags(self, config: GARSource) -> set[str]:
        images = await self._client.list_images(config)
        return {i.tag for i in images.all_images(hide_arch_specific=False)}

    @override
    async def prune_images(
        self,
        config: GARSource,
        policy: ImageFilterPolicy,
        *,
        dry_run: bool = True,
    ) -> list[str]:
        collection = await self._client.list_images(config)
        to_delete = collection.filter(
            policy,
            datetime.now(tz=UTC),
            invert=True,
            remove_arch_specific=False,
        )

        # Do the deletion if desired, and build the list of images that would
        # be deleted by tag.
        tags = []
        digests = []
        for image in to_delete:
            tags.append(image.tag)
            digests.append(image.digest)
        if not dry_run:
            await self._client.delete_images(config, digests)

        # Return the tags that were or would have been deleted.
        return tags
