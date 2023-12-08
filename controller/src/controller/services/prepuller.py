"""Prepull images to Kubernetes nodes."""

import asyncio

from safir.slack.blockkit import SlackException
from safir.slack.webhook import SlackWebhookClient
from structlog.stdlib import BoundLogger

from ..constants import PREPULLER_POD_TIMEOUT
from ..models.domain.rspimage import RSPImage
from ..storage.kubernetes.pod import PodStorage
from ..storage.metadata import MetadataStorage
from ..timeout import Timeout
from .builder.prepuller import PrepullerBuilder
from .image import ImageService

__all__ = ["Prepuller"]


class Prepuller:
    """Prepull images to Kubernetes nodes.

    There should be a singleton of this class in the lab controller process.
    It runs as a background task, prepulling images to nodes based on the
    information gathered by `~controller.services.image.ImageService`.

    Parameters
    ----------
    image_service
        Service to query for image information. Currently, the background
        refresh thread of the image service is also managed by this class.
    prepuller_builder
        Service that constructs prepuller Kubernetes objects.
    metadata_storage
        Storage layer for Nublado controller pod metadata.
    pod_storage
        Storage layer for managing Kubernetes pods.
    slack_client
        Optional Slack webhook client for alerts.
    logger
        Logger for messages.
    """

    def __init__(
        self,
        *,
        image_service: ImageService,
        prepuller_builder: PrepullerBuilder,
        metadata_storage: MetadataStorage,
        pod_storage: PodStorage,
        slack_client: SlackWebhookClient | None = None,
        logger: BoundLogger,
    ) -> None:
        self._image_service = image_service
        self._builder = prepuller_builder
        self._metadata = metadata_storage
        self._storage = pod_storage
        self._slack = slack_client
        self._logger = logger

    async def prepull_images(self) -> None:
        """Prepull missing images."""
        missing_by_node = self._image_service.missing_images_by_node()

        # Try to avoid hammering nodes by prepulling at most one image per
        # node at a time. We do this by creating a separate background task
        # per node, each of which works through the list of images that are
        # missing on that node.
        async with asyncio.TaskGroup() as tg:
            for node, images in missing_by_node.items():
                self._logger.debug(f"Creating prepull task for {node}")
                tg.create_task(self._prepull_images_for_node(node, images))
        self._logger.debug("Finished prepulling all images")

    async def _prepull_images_for_node(
        self, node: str, images: list[RSPImage]
    ) -> None:
        """Prepull a list of missing images on a single node.

        This runs as a background task, working through a set of images one
        after another until we have done them all. It runs in parallel with a
        similar task for each node.
        """
        image_tags = [i.tag for i in images]
        logger = self._logger.bind(images=image_tags, node=node)
        logger.info("Beginning prepulls for node")
        for image in images:
            await self._prepull_image(image, node)
            self._image_service.mark_prepulled(image, node)
        logger.info("Finished prepulls for node")

    async def _prepull_image(self, image: RSPImage, node: str) -> None:
        """Prepull an image on a single node.

        Parameters
        ----------
        image
            Image to prepull.
        node
            Node on which to prepull it.
        """
        namespace = self._metadata.namespace
        timeout = Timeout("Prepulling image", PREPULLER_POD_TIMEOUT)
        logger = self._logger.bind(node=node, image=image.tag)
        logger.debug("Prepulling image")
        pod = self._builder.build_pod(image, node)
        try:
            async with timeout.enforce():
                await self._storage.create(
                    namespace, pod, timeout, replace=True
                )
                await self._storage.delete_after_completion(
                    pod.metadata.name, namespace, timeout
                )
        except Exception as e:
            self._logger.exception("Failed to prepull image")
            if self._slack:
                if isinstance(e, SlackException):
                    await self._slack.post_exception(e)
                else:
                    await self._slack.post_uncaught_exception(e)
        else:
            self._logger.info("Prepulled image", delay=timeout.elapsed())
