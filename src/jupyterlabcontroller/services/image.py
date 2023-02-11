"""Container image service."""

from __future__ import annotations

import asyncio

from aiojobs import Scheduler
from safir.datetime import current_datetime
from structlog.stdlib import BoundLogger

from ..constants import IMAGE_REFRESH_INTERVAL
from ..models.domain.form import MenuImage, MenuImages
from ..models.domain.rspimage import RSPImage, RSPImageCollection
from ..models.domain.rsptag import (
    RSPImageTag,
    RSPImageTagCollection,
    RSPImageType,
)
from ..models.v1.prepuller import (
    Node,
    NodeImage,
    PrepulledImage,
    PrepullerImageStatus,
    PrepullerStatus,
    SpawnerImages,
)
from ..models.v1.prepuller_config import PrepullerConfiguration
from ..storage.docker import DockerStorageClient
from ..storage.k8s import K8sStorageClient

__all__ = ["ImageService"]


class ImageService:
    """Tracks the available images for Jupyter labs.

    There are two sources of images that can be used to spawn Jupyter labs:

    #. The tags in the Docker repository used as an image source. This is the
       full set of possible images; if it's not on this list, it can't be
       used. These are called the remote images.
    #. The images cached on the Kubernetes cluster nodes. This is the
       preferred set of images, since spawning one of these images will be
       fast. These are called the cached images.

    The lab controller is configured to prepull certain images to all nodes.
    That list is based on the Docker repository tags, filtered by the
    prepuller configuration. This service provides the list of tags that
    should be prepulled, the ones that have been prepulled, and the full list
    of available tags. This information is then used by the prepuller to
    determine what work it needs to do and by the lab controller API to
    determine which images to display in the menu.

    Parameters
    ----------
    config
        The prepuller configuration, used to determine the Docker registry and
        repository, and which tags should be prepulled.
    docker
        Client to query the Docker API for tags.
    kubernetes
        Client to query the Kubernetes cluster for cached images.
    logger
        Logger for messages.
    """

    def __init__(
        self,
        *,
        config: PrepullerConfiguration,
        docker: DockerStorageClient,
        kubernetes: K8sStorageClient,
        logger: BoundLogger,
    ) -> None:
        self._config = config
        self._docker = docker
        self._kubernetes = kubernetes
        self._logger = logger

        self._registry = self._config.registry
        self._repository = self._config.repository

        # Background task management.
        self._scheduler = Scheduler()
        self._lock = asyncio.Lock()
        self._refreshed = asyncio.Event()

        # All tags present in the registry and repository per its API.
        self._remote_tags = RSPImageTagCollection([])

        # Images that should be prepulled.
        self._to_prepull = RSPImageCollection([])

        # Mapping of node names to the images present on that node that are
        # members of the set of images we're prepulling. Used to calculate
        # missing images that the prepuller needs to pull.
        self._node_images: dict[str, RSPImageCollection] = {}

    def images(self) -> SpawnerImages:
        """All images available for spawning.

        Returns
        -------
        SpawnerImages
            Model suitable for returning from the route handler.
        """
        nodes = set(self._node_images.keys())

        recommended_tag = self._config.recommended_tag
        recommended = self._to_prepull.image_for_tag_name(recommended_tag)
        latest_weekly = self._to_prepull.latest(RSPImageType.WEEKLY)
        latest_daily = self._to_prepull.latest(RSPImageType.DAILY)
        latest_release = self._to_prepull.latest(RSPImageType.RELEASE)

        all_images = []
        for tag in self._remote_tags.all_tags():
            image = self._to_prepull.image_for_tag_name(tag.tag)
            if image:
                all_images.append(self._convert_image_for_api(image, nodes))
            else:
                all_images.append(self._convert_tag_for_api(tag))

        return SpawnerImages(
            recommended=self._convert_image_for_api(recommended, nodes),
            latest_weekly=self._convert_image_for_api(latest_weekly, nodes),
            latest_daily=self._convert_image_for_api(latest_daily, nodes),
            latest_release=self._convert_image_for_api(latest_release, nodes),
            all=all_images,
        )

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

        # Now, construct the dropdown of all possible tags. Where there is
        # overlap with the prepulled images, we will use the nicer information
        # from the prepulled image; otherwise, these pods will be spawned by
        # tag rather than digest.
        dropdown = []
        for tag in self._remote_tags.all_tags():
            if tag_image := self._to_prepull.image_for_tag_name(tag.tag):
                reference = tag_image.reference_with_digest
                entry = MenuImage(reference, tag_image.display_name)
            else:
                reference = f"{self._registry}/{self._repository}:{tag.tag}"
                entry = MenuImage(reference, tag.display_name)
            dropdown.append(entry)

        # Return the packaged results.
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
        prepull_image = self._to_prepull.image_for_tag_name(image.tag)
        if prepull_image:
            prepull_image.nodes.add(node)
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
            result[node] = list(to_pull.all_images())
        return result

    def prepull_status(self) -> PrepullerStatus:
        """Current prepuller status.

        Returns
        -------
        PrepullerStatus
            Model suitable for returning from a handler.
        """
        all_nodes = set(self._node_images.keys())
        nodes = {n: Node(name=n) for n in self._node_images.keys()}
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
            to_prepull = await self._get_remote()
            await self._get_node_images(to_prepull)
            self._to_prepull = to_prepull

    async def start(self) -> None:
        """Start a periodic refresh as a background task."""
        await self._scheduler.spawn(self._refresh_loop())

    async def stop(self) -> None:
        """Stop the background refresh task."""
        await self._scheduler.close()

    async def prepuller_wait(self) -> None:
        """Wait for a data refresh.

        This is meant to be called by the prepuller and only supports a single
        caller. It acts like a single-caller delay gate: each time it's
        called, it waits for a data refresh and then clears the event so that
        the next caller will wait again.
        """
        await self._refreshed.wait()
        self._refreshed.clear()

    async def _refresh_loop(self) -> None:
        """Run in the background by `start`, stopped with `stop`."""
        while True:
            start = current_datetime()
            try:
                await self.refresh()
                self._refreshed.set()
                delay = IMAGE_REFRESH_INTERVAL - (current_datetime() - start)
                if delay.total_seconds() < 1:
                    msg = "Image refresh is running continuously"
                    self._logger.warning(msg)
                else:
                    await asyncio.sleep(delay.total_seconds())
            except asyncio.CancelledError:
                break
            except Exception:
                # On failure, log the exception and do not indicate we hve
                # updated our data but otherwise continue as normal, including
                # the delay. This will provide some time for whatever the
                # problem was to be resolved.
                self._logger.exception("Unable to refresh image information")
                delay = IMAGE_REFRESH_INTERVAL - (current_datetime() - start)
                if delay.total_seconds() >= 1:
                    await asyncio.sleep(delay.total_seconds())

    def _convert_image_for_api(
        self, image: RSPImage | None, nodes: set[str]
    ) -> PrepulledImage | None:
        """Convert an image from the domain model to the API model.

        Parameters
        ----------
        image
            Domain model.
        nodes
            Eligible nodes. The image has been prepulled if it is present on
            all of these nodes.

        Returns
        -------
        PrepulledImage or None
            Corresponding API model, or `None` if the image was `None`.
        """
        if not image:
            return None
        aliases = list(image.aliases)
        if image.alias_target:
            aliases.append(image.alias_target)
        return PrepulledImage(
            reference=image.reference,
            tag=image.tag,
            aliases=aliases,
            name=image.display_name,
            digest=image.digest,
            prepulled=image.nodes >= nodes,
        )

    def _convert_tag_for_api(self, tag: RSPImageTag) -> PrepulledImage:
        """Convert from a tag to the API model.

        Parameters
        ----------
        tag
            Domain model of a tag

        Returns
        -------
        Image
            Corresponding API model.
        """
        return PrepulledImage(
            reference=f"{self._registry}/{self._repository}/{tag.tag}",
            tag=tag.tag,
            name=tag.display_name,
            prepulled=False,
        )

    async def _get_remote(self) -> RSPImageCollection:
        """Refresh remote tags and images from the Docker registry.

        Some of the tags are also converted to images, meaning that we also
        retrieve the digest for the image so that we can match it with cached
        images on nodes and resolve aliases.

        The collection of all remote tags is updated directly since that's
        safe, but it's not safe to update the collection of images to prepull
        until we've also checked Kubernetes to see which ones are cached.
        Otherwise, we'll think the images are missing from every node and do
        spurious prepulling. It is instead returned so that updating the
        object data can be deferred until Kubernetes data is also gathered.

        Returns
        -------
        jupyterlabcontroller.models.domain.rspimage.RSPImageCollection
            New collection of images to prepull.

        Notes
        -----
        Getting an image for a tag is an expensive operation, requiring a
        ``HEAD`` call to the Docker API for each image, so we only want to do
        this for images we care about, namely the images that we're going to
        prepull.

        The digest is retrieved again on each refresh because it may have
        changed (Docker registry tags are not immutable).
        """
        tags = await self._docker.list_tags(self._registry, self._repository)
        aliases = {self._config.recommended_tag} | set(self._config.alias_tags)
        tag_collection = RSPImageTagCollection.from_tag_names(
            tags, aliases, self._config.cycle
        )

        # Get digests for the prepulled images in parallel.
        to_prepull = self._subset_to_prepull(tag_collection)
        tasks = [
            asyncio.create_task(
                self._docker.get_image_digest(
                    self._registry, self._repository, tag.tag
                )
            )
            for tag in to_prepull.all_tags()
        ]
        digests = await asyncio.gather(*tasks)

        # Construct the images.
        images = []
        for tag, digest in zip(to_prepull.all_tags(), digests):
            image = RSPImage.from_tag(
                registry=self._registry,
                repository=self._repository,
                tag=tag,
                digest=digest,
            )
            images.append(image)

        # Turn this into a collection and return the new data. It's safe to
        # update our knowledge of all remote tags even if the rest of the data
        # update fails.
        self._remote_tags = tag_collection
        return RSPImageCollection(images)

    async def _get_node_images(self, to_prepull: RSPImageCollection) -> None:
        """Get the cached images on each Kubernetes node.

        Parameters
        ----------
        to_prepull
            Images that should be prepulled, and against which we compare
            cached images.
        """
        image_data = await self._kubernetes.get_image_data()

        # We only want to know about cached images with the same digest as a
        # remote image on the prepull list. Cached images with the same tag
        # but a different digest are out of date and should be ignored for the
        # purposes of determining which images have been successfully cached.
        # We can't do anything with cached images with no digest.
        image_lists = {}
        for node, node_images in image_data.items():
            images = []
            for node_image in node_images:
                digest = node_image.digest
                if not digest:
                    continue
                image = to_prepull.image_for_digest(digest)
                if image:
                    image.nodes.add(node)
                    image.size = node_image.size
                    images.append(image)
            image_lists[node] = images

        # Save the new data, converting the image lists to collections.
        self._node_images = {
            n: RSPImageCollection(i) for n, i in image_lists.items()
        }

    def _subset_to_prepull(
        self, tags: RSPImageTagCollection
    ) -> RSPImageTagCollection:
        """Determine the subset of remote images to prepull.

        Parameters
        ----------
        tags
            All remote images.

        Returns
        -------
        RSPImageTagCollection
            The subset of images that our configuration says we should
            prepull.
        """
        include = {self._config.recommended_tag}
        if self._config.pin:
            include.update(self._config.pin)
        return tags.subset(
            releases=self._config.num_releases,
            weeklies=self._config.num_weeklies,
            dailies=self._config.num_dailies,
            include=include,
        )
