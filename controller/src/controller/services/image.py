"""Container image service."""

from __future__ import annotations

import asyncio

from aiojobs import Scheduler
from safir.datetime import current_datetime
from safir.slack.webhook import SlackWebhookClient
from structlog.stdlib import BoundLogger

from ..constants import IMAGE_REFRESH_INTERVAL
from ..exceptions import UnknownDockerImageError
from ..models.domain.docker import DockerReference
from ..models.domain.form import MenuImage, MenuImages
from ..models.domain.kubernetes import KubernetesNodeImage
from ..models.domain.rspimage import RSPImage, RSPImageCollection
from ..models.domain.rsptag import RSPImageType
from ..models.v1.lab import ImageClass
from ..models.v1.prepuller import (
    Node,
    NodeImage,
    PrepulledImage,
    PrepullerImageStatus,
    PrepullerStatus,
    SpawnerImages,
)
from ..models.v1.prepuller_config import PrepullerConfig
from ..services.source.base import ImageSource
from ..storage.kubernetes.node import NodeStorage

__all__ = ["ImageService"]


class ImageService:
    """Service to track the available images for Jupyter labs.

    There are two places that contain a list of known lab images:

    #. The tags in the registry used as an image source. This is the full set
       of possible images; if it's not on this list, it can't be used. These
       are called the remote images.
    #. The images cached on the Kubernetes cluster nodes. This is the
       preferred set of images, since spawning one of these images will be
       fast. These are called the cached images.

    The lab controller is configured to prepull certain images to all nodes.
    That list is based on the registry tags, filtered by the prepuller
    configuration. This service provides the list of tags that should be
    prepulled, the ones that have been prepulled, and the full list of
    available tags. This information is then used by the prepuller to
    determine what work it needs to do and by the lab controller API to
    determine which images to display in the menu.

    Parameters
    ----------
    config
        The prepuller configuration, used to determine which tags should be
        prepulled and some other related information.
    source
        Source of remote images.
    node_storage
        Storage layer for Kubernetes nodes.
    slack_client
        Optional Slack client to use for alerts.
    logger
        Logger for messages.
    """

    def __init__(
        self,
        *,
        config: PrepullerConfig,
        source: ImageSource,
        node_storage: NodeStorage,
        slack_client: SlackWebhookClient | None = None,
        logger: BoundLogger,
    ) -> None:
        self._config = config
        self._source = source
        self._nodes = node_storage
        self._slack_client = slack_client
        self._logger = logger

        # Background task management.
        self._scheduler: Scheduler | None = None
        self._lock = asyncio.Lock()
        self._refreshed = asyncio.Event()

        # Images that should be prepulled.
        self._to_prepull = RSPImageCollection([])

        # Mapping of node names to the images present on that node that are
        # members of the set of images we're prepulling. Used to calculate
        # missing images that the prepuller needs to pull.
        self._node_images: dict[str, RSPImageCollection] = {}

    def image_for_class(self, image_class: ImageClass) -> RSPImage:
        """Determine the image by class keyword.

        Only prepulled images can be pulled by class keyword. So, for example,
        if no releases are prepulled, requesting ``latest-release`` will
        return an error. (However, this will still work before the images have
        been successfully prepulled.)

        Parameters
        ----------
        image_class
            Class of image requested.

        Returns
        -------
        RSPImage
            Corresponding image.

        Raises
        ------
        UnknownDockerImageError
            No available image of the requested class.
        """
        if image_class == ImageClass.RECOMMENDED:
            recommended_tag = self._config.recommended_tag
            image = self._to_prepull.image_for_tag_name(recommended_tag)
            if not image:
                raise UnknownDockerImageError("No recommended image found")
            return image

        if image_class == ImageClass.LATEST_RELEASE:
            image_type = RSPImageType.RELEASE
        elif image_class == ImageClass.LATEST_WEEKLY:
            image_type = RSPImageType.WEEKLY
        elif image_class == ImageClass.LATEST_DAILY:
            image_type = RSPImageType.DAILY
        image = self._to_prepull.latest(image_type)
        if not image:
            msg = f"No {image_class.value} image found"
            raise UnknownDockerImageError(msg)
        return image

    async def image_for_reference(
        self, reference: DockerReference
    ) -> RSPImage:
        """Determine the image corresponding to a Docker reference.

        Parameters
        ----------
        reference
            Docker reference, which may or may not have a digest.

        Returns
        -------
        RSPImage
            Corresponding image.
        """
        return await self._source.image_for_reference(reference)

    async def image_for_tag_name(self, tag_name: str) -> RSPImage:
        """Determine the image corresponding to a tag.

        Assume that the tag is for our configured registry and repository, and
        construct the corresponding
        `~controller.models.domain.rspimage.RSPImage`.

        Parameters
        ----------
        tag_name
            Tag of the image

        Returns
        -------
            Corresponding image.
        """
        return await self._source.image_for_tag_name(tag_name)

    def images(self) -> SpawnerImages:
        """All images available for spawning.

        Returns
        -------
        SpawnerImages
            Model suitable for returning from the route handler.
        """
        nodes = set(self._node_images.keys())

        recommended = self._config.recommended_tag
        images = {
            "recommended": self._to_prepull.image_for_tag_name(recommended),
            "latest_weekly": self._to_prepull.latest(RSPImageType.WEEKLY),
            "latest_daily": self._to_prepull.latest(RSPImageType.DAILY),
            "latest_release": self._to_prepull.latest(RSPImageType.RELEASE),
        }
        all_images = self._source.prepulled_images(nodes)

        # (Ab)using a dict comprehension is awkward, but otherwise the None
        # handling makes the code unreasonably verbose.
        spawner_images = {
            k: PrepulledImage.from_rsp_image(v, nodes) if v else None
            for k, v in images.items()
        }
        return SpawnerImages(all=all_images, **spawner_images)

    def menu_images(self) -> MenuImages:
        """Images that should appear in the menu.

        Returns
        -------
        MenuImages
            Information required to generate the spawner menu.
        """
        nodes = set(self._node_images.keys())

        # Construct the main menu only from prepulled tags. Pull out the
        # recommended tag and force it to be the first item on the menu,
        # regardless of any other sort rules.
        menu = []
        recommended = None
        for image in self._to_prepull.all_images(hide_aliased=True):
            entry = MenuImage(image.reference_with_digest, image.display_name)
            if image.tag == self._config.recommended_tag:
                recommended = entry
            elif image.nodes >= nodes:
                menu.append(entry)
        if recommended:
            menu.insert(0, recommended)

        # Get the dropdown menu of all possible images from the image source
        # and return the packaged results
        dropdown = self._source.menu_images()
        return MenuImages(menu=menu, dropdown=dropdown)

    def mark_prepulled(self, image: RSPImage, node: str) -> None:
        """Indicate we believe we have prepulled an image to a node.

        This optimistically updates our cached data to indicate that the given
        node now has that image. This may not be true, in which case we'll
        find that out during our next data refresh, but we want to be
        optimistic and allow this image to appear in the menu as soon as we
        think all the prepulls have completed.

        Parameters
        ----------
        image
            Image we just prepulled.
        node
            Node to which we prepulled it.
        """
        if self._to_prepull.image_for_digest(image.digest):
            self._source.mark_prepulled(image, node)
            self._node_images[node].add(image)

    def missing_images_by_node(self) -> dict[str, list[RSPImage]]:
        """Determine what images need to be cached.

        Returns
        -------
        dict of str to list
            Map of node names to a list of images that should be cached but do
            not appear to be.
        """
        result = {}
        for node, images in self._node_images.items():
            to_pull = self._to_prepull.subtract(images)
            to_pull_images = list(to_pull.all_images())
            if to_pull_images:
                result[node] = to_pull_images
        return result

    def prepull_status(self) -> PrepullerStatus:
        """Current prepuller status.

        Returns
        -------
        PrepullerStatus
            Model suitable for returning from a handler.
        """
        all_nodes = set(self._node_images.keys())
        nodes = {n: Node(name=n) for n in self._node_images}
        prepulled = []
        pending = []
        for image in self._to_prepull.all_images(hide_resolved_aliases=True):
            node_image = NodeImage(
                reference=image.reference,
                tag=image.tag,
                name=image.display_name,
                digest=image.digest,
                size=image.size,
                nodes=sorted(image.nodes),
            )
            if image.nodes >= all_nodes:
                prepulled.append(node_image)
            else:
                node_image.missing = sorted(all_nodes - image.nodes)
                pending.append(node_image)
            for node in image.nodes:
                nodes[node].cached.append(image.reference)
        return PrepullerStatus(
            config=self._config,
            images=PrepullerImageStatus(prepulled=prepulled, pending=pending),
            nodes=list(nodes.values()),
        )

    async def refresh(self) -> None:
        """Refresh data from Docker and Kubernetes.

        Normally run in the background by the task started with `start`, but
        can be called directly to force an immediate refresh. Does not catch
        exceptions; the caller must do that if desired.
        """
        async with self._lock:
            cached = await self._nodes.get_image_data()
            to_prepull = await self._source.update_images(self._config, cached)
            self._node_images = self._build_node_images(to_prepull, cached)
            self._to_prepull = to_prepull
            self._logger.info("Refreshed image information")

    async def start(self) -> None:
        """Start a periodic refresh as a background task.

        Does not return until the background refresh has completed its first
        run. We don't want to start answering user requests until we have
        populated our lists of available images; otherwise, we might return
        bogus information for the spawner form.
        """
        if self._scheduler:
            msg = "Image service already running, cannot start"
            self._logger.warning(msg)
            return
        self._logger.info("Starting image service")
        self._scheduler = Scheduler()
        await self._scheduler.spawn(self._refresh_loop())
        await self._refreshed.wait()

    async def stop(self) -> None:
        """Stop the background refresh task."""
        if not self._scheduler:
            self._logger.warning("Image service was already stopped")
            return
        self._logger.info("Stopping image service")
        await self._scheduler.close()
        self._scheduler = None

    async def prepuller_wait(self) -> None:
        """Wait for a data refresh.

        This is meant to be called by the prepuller and only supports a single
        caller. It acts like a single-caller delay gate: each time it's
        called, it waits for a data refresh and then clears the event so that
        the next caller will wait again.
        """
        await self._refreshed.wait()
        self._refreshed.clear()

    def _build_node_images(
        self,
        to_prepull: RSPImageCollection,
        node_cache: dict[str, list[KubernetesNodeImage]],
    ) -> dict[str, RSPImageCollection]:
        """Construct the collection of images on each node.

        Parameters
        ----------
        to_prepull
            Images that should be prepulled, and against which we compare
            cached images.
        node_cache
            Mapping of node names to the list of cached images on that node.

        Returns
        -------
        dict of str to RSPImageCollection
            Image collections of images found on each node.
        """
        image_collections = {}
        for node, node_images in node_cache.items():
            images = []
            for node_image in node_images:
                if not node_image.digest:
                    continue
                image = to_prepull.image_for_digest(node_image.digest)
                if not image:
                    continue
                images.append(image)
            image_collections[node] = RSPImageCollection(images)
        return image_collections

    async def _refresh_loop(self) -> None:
        """Run in the background by `start`, stopped with `stop`."""
        while True:
            start = current_datetime()
            try:
                await self.refresh()
                self._refreshed.set()
            except Exception as e:
                # On failure, log the exception and do not indicate we hve
                # updated our data but otherwise continue as normal, including
                # the delay. This will provide some time for whatever the
                # problem was to be resolved.
                self._logger.exception("Unable to refresh image information")
                if self._slack_client:
                    await self._slack_client.post_uncaught_exception(e)
            delay = IMAGE_REFRESH_INTERVAL - (current_datetime() - start)
            if delay.total_seconds() < 1:
                msg = "Image refresh is running continuously"
                self._logger.warning(msg)
            else:
                await asyncio.sleep(delay.total_seconds())