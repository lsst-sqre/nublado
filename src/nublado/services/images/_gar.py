"""Image manager implementation for the Google Artifact Registry API."""

from typing import override

from structlog.stdlib import BoundLogger

from ...models.images import GARSource
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
