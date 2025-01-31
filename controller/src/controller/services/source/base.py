"""Base class for image sources."""

from __future__ import annotations

from abc import ABCMeta, abstractmethod
from collections.abc import Mapping

from structlog.stdlib import BoundLogger

from ...models.domain.docker import DockerReference
from ...models.domain.image import MenuImage
from ...models.domain.kubernetes import KubernetesNodeImage
from ...models.domain.rspimage import RSPImage, RSPImageCollection
from ...models.v1.prepuller import ImageFilterOptions, PrepulledImage

__all__ = ["ImageSource"]


class ImageSource(metaclass=ABCMeta):
    """Base class for image sources.

    An image source is a class that wraps a Docker image registry, gathers
    information about known images, and answers questions about those images.
    It is used by the image service as the source of truth about remote
    images.

    This is the base class that defines the interface and some common code.

    Parameters
    ----------
    logger
        Logger for messages.
    """

    def __init__(self, logger: BoundLogger) -> None:
        self._logger = logger

    @abstractmethod
    async def image_for_reference(
        self, reference: DockerReference
    ) -> RSPImage:
        """Determine the image corresponding to a Docker reference.

        Parameters
        ----------
        reference
            Docker reference, which may or may not have a known digest.

        Returns
        -------
        RSPImage
            Corresponding image.
        """

    @abstractmethod
    async def image_for_tag_name(self, tag_name: str) -> RSPImage:
        """Determine the image corresponding to a tag.

        Assuming that the tag is for our image source, construct the
        corresponding `~controller.models.domain.rspimage.RSPImage`.

        Parameters
        ----------
        tag_name
            Tag of the image

        Returns
        -------
        RSPImage
            Corresponding image.
        """

    @abstractmethod
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

    @abstractmethod
    def menu_images(self) -> list[MenuImage]:
        """All known images suitable for display in the spawner menu.

        Returns
        -------
        list of MenuImage
            All known images.
        """

    @abstractmethod
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

    @abstractmethod
    async def update_images(
        self,
        prepull: ImageFilterOptions,
        node_cache: Mapping[str, list[KubernetesNodeImage]],
    ) -> RSPImageCollection:
        """Update image information and determine what images to prepull.

        Retrieve the full list of remote images, update their node presence
        information, and construct the subset to prepull.

        Parameters
        ----------
        prepull
            Configuration of what images to prepull.
        node_cache
            Mapping of node names to the list of cached images on that node.

        Returns
        -------
        RSPImageCollection
            Collection of images to prepull.
        """
