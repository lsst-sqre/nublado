"""Prepull images to Kubernetes nodes."""

import asyncio

from aiojobs import Scheduler
from safir.datetime import current_datetime
from safir.slack.blockkit import SlackException
from safir.slack.webhook import SlackWebhookClient
from structlog.stdlib import BoundLogger

from ..constants import IMAGE_REFRESH_INTERVAL, PREPULLER_POD_TIMEOUT
from ..models.domain.rspimage import RSPImage
from ..storage.kubernetes.pod import PodStorage
from ..storage.metadata import MetadataStorage
from .builder import PrepullerBuilder
from .image import ImageService

__all__ = ["Prepuller"]


class Prepuller:
    """Prepull images to Kubernetes nodes.

    There should be a singleton of this class in the lab controller process.
    It runs as a background task, prepulling images to nodes based on the
    information gathered by
    `~jupyterlabcontroller.services.image.ImageService`.

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
        self._slack_client = slack_client
        self._logger = logger

        # Scheduler to manage background tasks that prepull images to nodes.
        self._scheduler: Scheduler | None = None

    async def start(self) -> None:
        """Start the prepuller.

        The prepuller normally runs for the lifetime of the process in the
        background, but when first called, wait for the image data to populate
        in the foreground. This ensures that we populate image data before
        FastAPI completes its startup event, and therefore before we start
        answering requests. That in turn means a more accurate health check,
        since until we have populated image data our API is fairly useless.
        (It also makes life easier for the test suite.)
        """
        if self._scheduler:
            msg = "Prepuller already running, cannot start"
            self._logger.warning(msg)
            return
        self._logger.info("Starting prepuller tasks")
        await self._image_service.prepuller_wait()
        self._running = True
        self._scheduler = Scheduler()
        await self._scheduler.spawn(self._prepull_loop())

    async def stop(self) -> None:
        """Stop the prepuller."""
        if not self._scheduler:
            self._logger.warning("Prepuller was already stopped")
            return
        self._logger.info("Stopping prepuller")
        await self._scheduler.close()
        self._scheduler = None

    async def _prepull_loop(self) -> None:
        """Continually prepull images in a loop.

        When the prepuller is stopped, we will orphan prepuller pods. Avoiding
        this is difficult and unreliable. The prepuller should instead detect
        orphaned pods on startup and clean them up.
        """
        while True:
            try:
                await self.prepull_images()
                await self._image_service.prepuller_wait()
            except Exception as e:
                self._logger.exception("Uncaught exception in prepuller")
                if self._slack_client:
                    await self._slack_client.post_uncaught_exception(e)
                pause = IMAGE_REFRESH_INTERVAL.total_seconds()
                self._logger.warning("Pausing failed prepuller for {pause}s")
                await asyncio.sleep(pause)

    async def prepull_images(self) -> None:
        """Prepull missing images."""
        missing_by_node = self._image_service.missing_images_by_node()

        # Try to avoid hammering nodes by prepulling at most one image per
        # node at a time. We do this by creating a separate background task
        # per node, each of which works through the list of images that are
        # missing on that node.
        node_tasks = set()
        for node, images in missing_by_node.items():
            self._logger.debug(f"Creating prepull task for {node}")
            prepull_call = self._prepull_images_for_node(node, images)
            task = asyncio.create_task(prepull_call)
            node_tasks.add(task)
        await asyncio.gather(*node_tasks)
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
        start = current_datetime(microseconds=True)
        logger = self._logger.bind(node=node, image=image.tag)
        logger.debug("Prepulling image")
        try:
            pod = self._builder.build_pod(image, node)
            await self._storage.create(namespace, pod, replace=True)
            await self._storage.delete_after_completion(
                pod.metadata.name, namespace, timeout=PREPULLER_POD_TIMEOUT
            )
        except TimeoutError:
            now = current_datetime(microseconds=True)
            delay = (now - start).total_seconds()
            msg = f"Timed out prepulling image after {delay}s"
            logger.warning(msg)
        except Exception as e:
            self._logger.exception("Failed to prepull image")
            if self._slack_client:
                if isinstance(e, SlackException):
                    await self._slack_client.post_exception(e)
                else:
                    await self._slack_client.post_uncaught_exception(e)
        else:
            now = current_datetime(microseconds=True)
            delay = (now - start).total_seconds()
            self._logger.info("Prepulled image", delay=delay)
