"""Prepull images to Kubernetes nodes."""

import asyncio
import re
from pathlib import Path
from typing import Optional

from aiojobs import Scheduler
from kubernetes_asyncio.client import V1Container, V1OwnerReference, V1PodSpec
from safir.slack.blockkit import SlackException
from safir.slack.webhook import SlackWebhookClient
from structlog.stdlib import BoundLogger

from ..constants import IMAGE_REFRESH_INTERVAL
from ..models.domain.rspimage import RSPImage
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
    namespace
        Namespace in which to put prepuller pods.
    metadata_path
        Path to injected pod metadata used to create the owner reference for
        prepull pods.
    image_service
        Service to query for image information. Currently, the background
        refresh thread of the image service is also managed by this class.
    k8s_client
        Client for talking to Kubernetes.
    slack_client
        Optional Slack webhook client for alerts.
    logger
        Logger for messages.
    """

    def __init__(
        self,
        *,
        namespace: str,
        metadata_path: Path,
        image_service: ImageService,
        k8s_client: K8sStorageClient,
        slack_client: Optional[SlackWebhookClient] = None,
        logger: BoundLogger,
    ) -> None:
        self._namespace = namespace
        self._metadata_path = metadata_path
        self._image_service = image_service
        self._k8s_client = k8s_client
        self._slack_client = slack_client
        self._logger = logger

        # Scheduler to manage background tasks that prepull images to nodes.
        self._scheduler: Optional[Scheduler] = None

    async def start(self) -> None:
        if self._scheduler:
            msg = "Prepuller already running, cannot start"
            self._logger.warning(msg)
            return
        self._logger.info("Starting prepuller tasks")

        # Wait for the image data to populate in the foreground. This ensures
        # that we populate image data before FastAPI completes its startup
        # event, and therefore before we start answering requests. That in
        # turn means a more accurate health check, since until we have
        # populated image data our API is fairly useless. (It also makes life
        # easier for the test suite.)
        await self._image_service.prepuller_wait()
        self._running = True
        self._scheduler = Scheduler()
        await self._scheduler.spawn(self._prepull_loop())

    async def stop(self) -> None:
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
        name = self._prepull_pod_name(image, node)
        namespace = self._namespace
        logger = self._logger.bind(pod=name, namespace=namespace)
        logger.debug(f"Prepulling {image.tag} on {node}")
        try:
            await self._k8s_client.create_pod(
                name=name,
                namespace=namespace,
                pod_spec=self._prepull_pod_spec(image, node),
                owner=self._prepull_pod_owner(),
            )
            async for event in self._k8s_client.wait_for_pod(name, namespace):
                logger.debug(f"Saw pod event: {event.message}")
                if event.error:
                    logger.error(f"Error in prepuller pod: {event.error}")
            await self._k8s_client.remove_completed_pod(name, namespace)
        except Exception as e:
            self._logger.exception(f"Failed to prepull {image.tag} on {node}")
            if self._slack_client:
                if isinstance(e, SlackException):
                    await self._slack_client.post_exception(e)
                else:
                    await self._slack_client.post_uncaught_exception(e)
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
        image_tags = [i.tag for i in images]
        self._logger.info(f"Beginning prepulls for {node}", images=image_tags)
        for image in images:
            await self._prepull_image(image, node)
            self._image_service.mark_prepulled(image, node)
        self._logger.info(f"Finished prepulls for {node}", images=image_tags)

    def _prepull_pod_name(self, image: RSPImage, node: str) -> str:
        """Create the pod name to use for prepulling an image.

        This embeds some information in the pod name that may be useful for
        debugging purposes.

        Parameters
        ----------
        image
            Image to prepull.
        node
            Node on which to prepull it.

        Returns
        -------
        str
            Pod name to use.
        """
        tag_part = image.tag.replace("_", "-")
        tag_part = re.sub(r"[^\w.-]", "", tag_part, flags=re.ASCII)
        name = f"prepull-{tag_part}-{node}"

        # Kubernetes object names may be at most 253 characters long.
        return name[:253]

    def _prepull_pod_owner(self) -> V1OwnerReference | None:
        """Construct the owner reference to attach to prepuller pods.

        We want all prepuller pods to show as owned by the lab controller,
        both for clearer display in services such as Argo CD and also so that
        Kubernetes will delete the pods when the lab controller restarts,
        avoiding later conflicts.

        Returns
        -------
        V1OwnerReference or None
            Owner reference to use for prepuller pods or `None` if no pod
            metadata for the lab controller is available.
        """
        name_path = self._metadata_path / "name"
        uid_path = self._metadata_path / "uid"
        if not (name_path.exists() and uid_path.exists()):
            return None
        return V1OwnerReference(
            api_version="v1",
            kind="Pod",
            name=name_path.read_text().strip(),
            uid=uid_path.read_text().strip(),
            block_owner_deletion=True,
        )
