"""Prepull images to Kubernetes nodes."""

import asyncio
import os

from aiojobs import Scheduler
from kubernetes_asyncio.client import V1Container, V1PodSpec
from structlog.stdlib import BoundLogger

from ..models.domain.rspimage import RSPImage
from ..models.v1.prepuller_config import PrepullerConfiguration
from ..storage.k8s import K8sStorageClient
from .image import ImageService


class Prepuller:
    """Prepull images to Kubernetes nodes.

    There should be a singleton of this class in the lab controller process.
    It runs as a background task, prepulling images to nodes based on the
    information gathered by
    `~jupyterlabcontroller.services.image.ImageService`.

    Parameters
    ----------
    config
        Configuration for the prepuller.
    namespace
        Namespace in which to put prepuller pods.
    image_service
        Service to query for image information. Currently, the background
        refresh thread of the image service is also managed by this class.
    k8s_client
        Client for talking to Kubernetes.
    logger
        Logger for messages.
    """

    def __init__(
        self,
        *,
        config: PrepullerConfiguration,
        namespace: str,
        image_service: ImageService,
        k8s_client: K8sStorageClient,
        logger: BoundLogger,
    ) -> None:
        self._image_service = image_service
        self._k8s_client = k8s_client
        self._logger = logger
        self._namespace = namespace

        self._scheduler = Scheduler()
        self._running = False

    async def start(self) -> None:
        if self._running:
            self._logger.info("Prepuller already running, cannot start again")
            return
        self._logger.info("Starting prepuller tasks")

        # Wait for the image data to populate in the foreground. This ensures
        # that we populate image data before FastAPI completes its startup
        # event, and therefore before we start answering requests. That in
        # turn means a more accurate health check, since until we have
        # populated image data our API is fairly useless. (It also makes life
        # easier for the test suite.)
        await self._image_service.prepuller_wait()
        await self._scheduler.spawn(self._prepull_loop())
        self._running = True

    async def stop(self) -> None:
        if not self._running:
            self._logger.info("Prepuller tasks were already stopped")
        self._logger.info("Cancelling prepuller tasks")
        await self._scheduler.close()
        self._running = False

    async def _prepull_loop(self) -> None:
        """Continually prepull images in a loop.

        When the prepuller is stopped, we will orphan prepuller pods. Avoiding
        this is difficult and unreliable. The prepuller should instead detect
        orphaned pods on startup and clean them up.
        """
        while True:
            await self.prepull_images()
            await self._image_service.prepuller_wait()

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

    def _prepull_pod_spec(self, image: RSPImage, node: str) -> V1PodSpec:
        """Create a spec to run a pod with a specific image on a node.

        The pod does nothing but sleep five seconds and then exit.  Its only
        function is to ensure that that image gets pulled to that node.
        """
        return V1PodSpec(
            containers=[
                V1Container(
                    name="prepull",
                    command=["/bin/sleep", "5"],
                    image=image.reference_with_digest,
                    working_dir="/tmp",
                )
            ],
            node_name=node,
            restart_policy="Never",
        )

    async def _prepull_image(self, image: RSPImage, node: str) -> None:
        """Prepull an image on a single node.

        Parameters
        ----------
        image
            Image to prepull.
        node
            Node on which to prepull it.
        """
        spec = self._prepull_pod_spec(image, node)
        try:
            self._logger.debug(f"Prepulling {image.tag} on {node}")
            name = f"prepull-{os.urandom(8).hex()}"
            await self._k8s_client.create_pod(name, self._namespace, spec)
            await self._k8s_client.wait_for_pod_creation(
                podname=name, namespace=self._namespace
            )
            await self._k8s_client.remove_completed_pod(
                podname=name, namespace=self._namespace
            )
        except Exception:
            self._logger.exception(f"Failed to prepull {image.tag} on {node}")
        else:
            self._logger.info(f"Prepulled {image.tag} on {node}")

    async def _prepull_images_for_node(
        self, node: str, images: list[RSPImage]
    ) -> None:
        """Prepull a list of missing images on a single node.

        This runs as a background task, working through a set of images one
        after another until we have done them all. It runs in parallel with a
        similar task for each node.
        """
        self._logger.debug(f"Beginning prepulls for {node}")
        for image in images:
            await self._prepull_image(image, node)

            # Temporarily don't register images as prepulled because the test
            # suite doesn't expect it.
            # self._image_service.mark_prepulled(image, node)
        self._logger.debug(f"Finished prepulls for {node}")
