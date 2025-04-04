"""Image source using a Google Artifact Registry."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import override

from structlog.stdlib import BoundLogger

from ...exceptions import InvalidDockerReferenceError, UnknownDockerImageError
from ...models.domain.docker import DockerReference
from ...models.domain.image import MenuImage
from ...models.domain.imagefilterpolicy import RSPImageFilterPolicy
from ...models.domain.kubernetes import KubernetesNodeImage
from ...models.domain.rspimage import RSPImage, RSPImageCollection
from ...models.v1.prepuller import (
    GARSourceOptions,
    PrepulledImage,
    PrepullerOptions,
)
from ...storage.gar import GARStorageClient
from .base import ImageSource

__all__ = ["GARImageSource"]


class GARImageSource(ImageSource):
    """Image source using a Google Artifact Registry.

    Google Artifact Registry has a much nicer API that returns all available
    images with their aliases and hashes in one request. This means we don't
    have to track tags and images separately and the logic is much simpler
    than `~controller.services.source.docker.DockerImageSource`.

    Parameters
    ----------
    config
        Source configuration for which server, project, and image to use.
    gar
        Google Artifact Registry client.
    logger
        Logger for messages.
    image_filter
        Filter policy to apply to images in the remote registry.
    """

    def __init__(
        self,
        config: GARSourceOptions,
        gar: GARStorageClient,
        logger: BoundLogger,
        image_filter: RSPImageFilterPolicy,
    ) -> None:
        super().__init__(logger, image_filter)
        self._config = config
        self._gar = gar

        # All available images.
        self._images = RSPImageCollection([])

    @override
    async def image_for_reference(
        self, reference: DockerReference
    ) -> RSPImage:
        """Determine the image corresponding to a Docker reference.

        Parameters
        ----------
        reference
            Docker reference.

        Returns
        -------
        RSPImage
            Corresponding image.

        Raises
        ------
        InvalidDockerReferenceError
            Raised if the Docker reference doesn't contain a tag. References
            without a tag are valid references to Docker, but for our purposes
            we always want to have a tag to use for debugging, status display
            inside the lab, etc.
        UnknownDockerImageError
            Raised if this is not one of the remote images we know about.
        """
        if reference.digest:
            image = self._images.image_for_digest(reference.digest)
        elif reference.tag is None:
            msg = f'Docker reference "{reference}" has no tag'
            raise InvalidDockerReferenceError(msg)
        else:
            image = self._images.image_for_tag_name(reference.tag)
        if (
            not image
            or reference.registry != self._config.registry
            or reference.repository != self._config.path
        ):
            msg = f'Docker reference "{reference}" not found'
            raise UnknownDockerImageError(msg)
        return image

    @override
    async def image_for_tag_name(self, tag_name: str) -> RSPImage:
        """Determine the image corresponding to a tag.

        Assuming the tag is for our configured image, find the
        corresponding `~controller.models.domain.rspimage.RSPImage`.

        Parameters
        ----------
        tag_name
            Tag of the image

        Returns
        -------
            Corresponding image.

        Raises
        ------
        UnknownDockerImageError
            The requested tag is not found.
        """
        image = self._images.image_for_tag_name(tag_name)
        if not image:
            raise UnknownDockerImageError(f'Docker tag "{tag_name}" not found')
        return image

    @override
    def mark_prepulled(self, image: RSPImage, node: str) -> None:
        """Optimistically mark an image as prepulled to a node.

        Called by the prepuller after the prepull pod succeeded.

        Parameters
        ----------
        tag_name
            Tag of image.
        node
            Node to which the image was prepulled.
        """
        self._images.mark_image_seen_on_node(image.digest, node)

    @override
    def menu_images(self) -> list[MenuImage]:
        """All known images suitable for display in the spawner menu.

        Returns
        -------
        list of MenuImage
            All known images meeting filter criteria.
        """
        return [
            MenuImage(i.reference_with_digest, i.display_name)
            for i in self._images.filter(
                self._image_filter, datetime.now(tz=UTC)
            )
        ]

    @override
    def prepulled_images(self, nodes: set[str]) -> list[PrepulledImage]:
        """All known images with their prepulled status in the API model.

        Parameters
        ----------
        nodes
            Nodes on which the image must exist to qualify as prepulled.

        Returns
        -------
        list of PrepulledImage
            All known images.
        """
        return [
            PrepulledImage.from_rsp_image(i, nodes)
            for i in self._images.all_images()
        ]

    @override
    async def update_images(
        self,
        prepull: PrepullerOptions,
        node_cache: Mapping[str, list[KubernetesNodeImage]],
    ) -> RSPImageCollection:
        """Update image information and determine what images to prepull.

        Parameters
        ----------
        prepull
            Configuration of what images to prepull.
        node_cache
            Mapping of node names to the list of cached images on that node.

        Returns
        -------
        RSPImageCollection
            New collection of images to prepull.
        """
        images = await self._gar.list_images(self._config, prepull.cycle)

        # Set their node presence information based on node cache data.
        for node, node_images in node_cache.items():
            for node_image in node_images:
                if not node_image.digest:
                    continue
                images.mark_image_seen_on_node(node_image.digest, node)
        self._images = images

        # Construct the subset to prepull.
        include = {prepull.recommended_tag}
        if prepull.pin:
            include.update(prepull.pin)
        return images.subset(
            releases=prepull.num_releases,
            weeklies=prepull.num_weeklies,
            dailies=prepull.num_dailies,
            include=include,
        )
