"""Client for Google Artifact Registry."""

from __future__ import annotations

from google.cloud import artifactregistry_v1
from google.cloud.artifactregistry_v1 import ListDockerImagesRequest
from structlog.stdlib import BoundLogger

from ..models.domain.arch_filter import filter_arch_tags
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
        """Return all images stored in the remote repository.

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
        request = ListDockerImagesRequest(parent=config.parent)
        image_list = await self._client.list_docker_images(request=request)

        images = []
        async for gar_image in image_list:
            uri = gar_image.uri
            # Isolate everything after last slash (if any).
            last_component = uri.split("/")[-1]
            # Then split that on the at-sign.
            img_name, digest = last_component.rsplit("@", 1)
            if img_name != config.image:
                # One repository may host many images.  We only want the
                # ones whose names match the one we're spawning.
                continue
            filtered_tags = filter_arch_tags(list(gar_image.tags))
            for tag_name in filtered_tags:
                tag = RSPImageTag.from_str(tag_name)
                image = RSPImage.from_tag(
                    registry=config.registry,
                    repository=config.path,
                    tag=tag,
                    digest=digest,
                )
                image.size = gar_image.image_size_bytes
                images.append(image)

        self._logger.debug(
            "Listed all images",
            location=config.location,
            project_id=config.project_id,
            repository=config.repository,
            image=config.image,
            count=len(images),
        )

        return RSPImageCollection(images, cycle=cycle)
