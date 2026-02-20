"""Client for Google Artifact Registry."""

import asyncio

from google.api_core.exceptions import ServiceUnavailable
from google.cloud import artifactregistry_v1
from google.cloud.artifactregistry_v1 import ListDockerImagesRequest
from structlog.stdlib import BoundLogger

from ..constants import GAR_RETRY_DELAY, GAR_RETRY_LIMIT
from ..models.domain.rspimage import RSPImage, RSPImageCollection
from ..models.domain.rsptag import RSPImageTag
from ..models.v1.prepuller import GARSourceOptions

__all__ = ["GARStorageClient"]


class GARStorageClient:
    """Client for Google Artifact Registry.

    This client doesn't handle authentication and instead assumes that the
    default credentials will be sufficient. It should be run using workload
    identity.

    Parameters
    ----------
    logger
        Logger for messages.
    """

    def __init__(self, logger: BoundLogger) -> None:
        self._logger = logger
        self._client = artifactregistry_v1.ArtifactRegistryAsyncClient()

    async def list_images(
        self, config: GARSourceOptions, cycle: int | None = None
    ) -> RSPImageCollection:
        """Return images stored in the remote repository, with arch-specific
        images filtered out if a corresponding base image exists.

        Parameters
        ----------
        config
            Path to a specific image name in Google Artifact Registry.
        cycle
            If not `None`, restrict to images with the given SAL cycle.

        Returns
        -------
        RSPImageCollection
            All images stored with that name.
        """
        logger = self._logger.bind(
            location=config.location,
            project_id=config.project_id,
            repository=config.repository,
            image=config.image,
        )

        # Requests to the Google API periodically fail in the middle of the
        # request with 503 Authentication server unavailable, so retry up to
        # GAR_RETRY_LIMIT times, pausing for GAR_DELAY after each failure.
        images = None
        for attempt in range(GAR_RETRY_LIMIT):
            try:
                images = await self._fetch_image_list(config)
            except ServiceUnavailable as e:
                msg = "Error listing images from GAR, retrying"
                error = f"{type(e).__name__}: {e!s}"
                logger.warning(msg, error=error, attempt=attempt)
                await asyncio.sleep(GAR_RETRY_DELAY.total_seconds())
            else:
                break

        # If we still don't have an image list, try one more time and raise an
        # uncaught exception if it still fails.
        if not images:
            images = await self._fetch_image_list(config)

        # Assemble the resulting collection of images and return it.
        logger.debug("Listed all images", count=len(images))
        return RSPImageCollection(images, cycle=cycle)

    async def _fetch_image_list(
        self, config: GARSourceOptions
    ) -> list[RSPImage]:
        """Fetch the list of images from Google.

        Retrieve the list of images from Google Artifact Registry and parse
        them into `~nublado.controller.models.domain.rspimage.RSPImage`
        objects. This is broken out into a separate method so that it can be
        retried.

        Parameters
        ----------
        config
            Path to a specific image name in Google Artifact Registry.

        Yields
        ------
        RSPImage
            The next image in the list at Google.
        """
        request = ListDockerImagesRequest(parent=config.parent)
        image_list = await self._client.list_docker_images(request=request)

        # Parse the results and extract the image tags and digests. The last
        # component of the URI will be the image name and hash separated by @.
        # Ignore entries for non-matching images since there may be multiple
        # images in the same repository.
        images = []
        async for gar_image in image_list:
            image_name, digest = gar_image.uri.split("/")[-1].split("@", 1)
            if image_name != config.image:
                continue
            for tag in gar_image.tags:
                image = RSPImage.from_tag(
                    RSPImageTag.from_str(tag),
                    registry=config.registry,
                    repository=config.path,
                    digest=digest,
                    size=gar_image.image_size_bytes,
                )
                images.append(image)

        # Return the results.
        return images
