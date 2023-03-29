"""Container image service."""

from __future__ import annotations

import asyncio
from abc import ABCMeta, abstractmethod
from typing import Generic, Optional, TypeVar

from aiojobs import Scheduler
from safir.datetime import current_datetime
from structlog.stdlib import BoundLogger

from ..constants import IMAGE_REFRESH_INTERVAL
from ..exceptions import InvalidDockerReferenceError, UnknownDockerImageError
from ..models.domain.docker import DockerReference
from ..models.domain.form import MenuImage, MenuImages
from ..models.domain.rspimage import RSPImage, RSPImageCollection
from ..models.domain.rsptag import (
    RSPImageTag,
    RSPImageTagCollection,
    RSPImageType,
)
from ..models.v1.lab import ImageClass
from ..models.v1.prepuller import (
    Node,
    NodeImage,
    PrepulledImage,
    PrepullerImageStatus,
    PrepullerStatus,
    SpawnerImages,
)
from ..models.v1.prepuller_config import (
    PrepullerConfigDocker,
    PrepullerConfigGAR,
)
from ..storage.docker import DockerStorageClient
from ..storage.gar import GARStorageClient
from ..storage.k8s import K8sStorageClient

T = TypeVar("T", bound=PrepullerConfigDocker | PrepullerConfigGAR)

__all__ = [
    "DockerImageService",
    "GARImageService",
    "ImageService",
]


class ImageService(Generic[T], metaclass=ABCMeta):
    """Base service to tracks the available images for Jupyter labs.

    This class provides the generic interface and shared code. There are
    specializations of this object for each possible source of lab images.

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
        The prepuller configuration, used to determine the Docker registry and
        repository, and which tags should be prepulled.
    kubernetes
        Client to query the Kubernetes cluster for cached images.
    logger
        Logger for messages.
    """

    def __init__(
        self,
        config: T,
        kubernetes: K8sStorageClient,
        logger: BoundLogger,
    ) -> None:
        self._config = config
        self._kubernetes = kubernetes
        self._logger = logger

        # Background task management.
        self._scheduler: Optional[Scheduler] = None
        self._lock = asyncio.Lock()
        self._refreshed = asyncio.Event()

        # Images that should be prepulled.
        self._to_prepull = RSPImageCollection([])

        # Mapping of node names to the images present on that node that are
        # members of the set of images we're prepulling. Used to calculate
        # missing images that the prepuller needs to pull.
        self._node_images: dict[str, RSPImageCollection] = {}

    @abstractmethod
    def all_images_with_prepulled_status(
        self, nodes: set[str]
    ) -> list[PrepulledImage]:
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
    async def get_remote_images(self) -> RSPImageCollection:
        """Get the collection of images to prepull.

        This will also update the internal understanding of all available
        remote images. How this is stored depends on the remote image source,
        and thus is not specified in this base class.

        Returns
        -------
        RSPImageCollection
            Collection of images to prepull.
        """

    @abstractmethod
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

    @abstractmethod
    async def image_for_tag_name(self, tag_name: str) -> RSPImage:
        """Determine the image corresponding to a tag.

        Assume that the tag is for our configured registry and repository, and
        construct the corresponding
        `~jupyterlabcontroller.models.domain.rspimage.RSPImage`.

        Parameters
        ----------
        tag_name
            Tag of the image

        Returns
        -------
            Corresponding image.
        """

    def image_for_class(self, image_class: ImageClass) -> RSPImage:
        """Determine the image by class keyword.

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
        all_images = self.all_images_with_prepulled_status(nodes)

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

        # Now, construct the dropdown of all possible tags. Where there is
        # overlap with the prepulled images, we will use the nicer information
        # from the prepulled image; otherwise, these pods will be spawned by
        # tag rather than digest.
        all_images = self.all_images_with_prepulled_status(nodes)
        dropdown = []
        for prepulled_image in all_images:
            reference = prepulled_image.reference
            if prepulled_image.digest:
                reference += "@" + prepulled_image.digest
            dropdown.append(MenuImage(reference, prepulled_image.name))

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
            for alias in prepull_image.aliases:
                alias_image = self._to_prepull.image_for_tag_name(alias)
                if alias_image:
                    alias_image.nodes.add(node)
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
            to_prepull = await self.get_remote_images()
            self._node_images = await self._get_node_images(to_prepull)
            self._to_prepull = to_prepull

    async def start(self) -> None:
        """Start a periodic refresh as a background task.

        Does not return until the background refresh has completed its first
        run. We don't want to start answering user requests until we have
        populated our lists of available images; otherwise, we might return
        bogus information for the spawner form.
        """
        if self._scheduler:
            msg = "Image service already running, cannot start again"
            self._logger.warning(msg)
            return
        self._logger.info("Starting image service")
        self._scheduler = Scheduler()
        await self._scheduler.spawn(self._refresh_loop())
        await self._refreshed.wait()

    async def stop(self) -> None:
        """Stop the background refresh task."""
        if not self._scheduler:
            self._logger.warning("Prepuller tasks were already stopped")
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

    async def _get_node_images(
        self, to_prepull: RSPImageCollection
    ) -> dict[str, RSPImageCollection]:
        """Get the cached images on each Kubernetes node.

        Parameters
        ----------
        to_prepull
            Images that should be prepulled, and against which we compare
            cached images.

        Returns
        -------
        dict of str to RSPImageCollection
            Image collections of images found on each node.
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
                if not image:
                    continue
                image.nodes.add(node)
                image.size = node_image.size
                images.append(image)
                for alias in image.aliases:
                    alias_image = to_prepull.image_for_tag_name(alias)
                    if alias_image:
                        alias_image.nodes.add(node)
                        alias_image.size = node_image.size
            image_lists[node] = images

        # Save the new data, converting the image lists to collections.
        return {n: RSPImageCollection(i) for n, i in image_lists.items()}


class DockerImageService(ImageService):
    """Specialization of `ImageService` that uses a Docker registry.

    Docker has a very awkward API that makes it expensive to get the hash of
    an image or to see which tags alias each other. The Docker specialization
    of the `ImageService` therefore has to juggle both tag collections (all
    known tags, possibly without hashes) and image collections (images fully
    resolved with tags).

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
        config: PrepullerConfigDocker,
        docker: DockerStorageClient,
        kubernetes: K8sStorageClient,
        logger: BoundLogger,
    ) -> None:
        super().__init__(config, kubernetes, logger)
        self._docker = docker

        # All tags present in the registry and repository per its API.
        self._remote_tags = RSPImageTagCollection([])

    def all_images_with_prepulled_status(
        self, nodes: set[str]
    ) -> list[PrepulledImage]:
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
        all_images = []
        for tag in self._remote_tags.all_tags():
            image = self._to_prepull.image_for_tag_name(tag.tag)
            if image:
                api_image = PrepulledImage.from_rsp_image(image, nodes)
            else:
                api_image = self._convert_tag_for_api(tag)
            if api_image:
                all_images.append(api_image)
        return all_images

    async def image_for_reference(
        self, reference: DockerReference
    ) -> RSPImage:
        """Determine the image corresponding to a Docker reference.

        If the reference doesn't contain a digest, this may require a call to
        the Docker API to determine the digest. The results are intentionally
        not cached since references without digests indicate we're pulling an
        image by tag, and we should therefore always use the latest version.

        Parameters
        ----------
        reference
            Docker reference, which may or may not have a digest.

        Returns
        -------
        RSPImage
            Corresponding image.

        Raises
        ------
        DockerRegistryError
            Raised if retrieving the digest from the Docker Registry failed.
        InvalidDockerReferenceError
            Raised if the Docker reference doesn't contain a tag or is not one
            of the remote images we know about. References without a tag are
            valid references to Docker, but for our purposes we always want to
            have a tag to use for debugging, status display inside the lab,
            etc.
        UnknownDockerImageError
            Raised if this is not one of the remote images we know about.
        """
        if reference.tag is None:
            msg = f'Docker reference "{reference}" has no tag'
            raise InvalidDockerReferenceError(msg)

        # If the image was prepulled, we already have an RSPImage for it.
        image = self._to_prepull.image_for_tag_name(reference.tag)
        if image:
            if (
                reference.registry != image.registry
                or reference.repository != image.repository
            ):
                msg = f'Docker reference "{reference}" not found'
                raise UnknownDockerImageError(msg)
            return image

        # Otherwise, retrieve the RSPImageTag for the image to ensure that it
        # was in the list of available remote images.
        tag = self._remote_tags.tag_for_tag_name(reference.tag)
        if (
            not tag
            or reference.registry != self._config.docker.registry
            or reference.repository != self._config.docker.repository
        ):
            msg = f'Docker reference "{reference}" not found'
            raise UnknownDockerImageError(msg)

        # We found the tag and can resolve this reference to an RSPImage.
        if reference.digest:
            digest = reference.digest
        else:
            digest = await self._docker.get_image_digest(
                reference.registry, reference.repository, reference.tag
            )
        return RSPImage.from_tag(
            registry=reference.registry,
            repository=reference.repository,
            tag=tag,
            digest=digest,
        )

    async def image_for_tag_name(self, tag_name: str) -> RSPImage:
        """Determine the image corresponding to a tag.

        Assume that the tag is for our configured registry and repository, and
        construct the corresponding
        `~jupyterlabcontroller.models.domain.rspimage.RSPImage`.

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
        DockerRegistryError
            Unable to retrieve the digest from the Docker Registry.
        """
        tag = self._remote_tags.tag_for_tag_name(tag_name)
        if not tag:
            raise UnknownDockerImageError(f"Docker tag {tag_name} not found")
        digest = await self._docker.get_image_digest(
            self._config.docker.registry,
            self._config.docker.repository,
            tag_name,
        )
        return RSPImage.from_tag(
            registry=self._config.docker.registry,
            repository=self._config.docker.repository,
            tag=tag,
            digest=digest,
        )

    async def get_remote_images(self) -> RSPImageCollection:
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
        RSPImageCollection
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
        tags = await self._docker.list_tags(
            self._config.docker.registry, self._config.docker.repository
        )
        aliases = {self._config.recommended_tag} | set(self._config.alias_tags)
        tag_collection = RSPImageTagCollection.from_tag_names(
            tags, aliases, self._config.cycle
        )

        # Get digests for the prepulled images in parallel.
        to_prepull = self._subset_to_prepull(tag_collection)
        tasks = [
            asyncio.create_task(
                self._docker.get_image_digest(
                    self._config.docker.registry,
                    self._config.docker.repository,
                    tag.tag,
                )
            )
            for tag in to_prepull.all_tags()
        ]
        digests = await asyncio.gather(*tasks)

        # Construct the images.
        images = []
        for tag, digest in zip(to_prepull.all_tags(), digests):
            image = RSPImage.from_tag(
                registry=self._config.docker.registry,
                repository=self._config.docker.repository,
                tag=tag,
                digest=digest,
            )
            images.append(image)

        # Turn this into a collection and return the new data. It's safe to
        # update our knowledge of all remote tags even if the rest of the data
        # update fails.
        self._remote_tags = tag_collection
        return RSPImageCollection(images)

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
        registry = self._config.docker.registry
        repository = self._config.docker.repository
        return PrepulledImage(
            reference=f"{registry}/{repository}:{tag.tag}",
            tag=tag.tag,
            name=tag.display_name,
            prepulled=False,
        )

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


class GARImageService(ImageService):
    """Specialization of `ImageService` that uses Google Artifact Registry.

    Google Artifact Registry has a much nicer API that returns all available
    images with their aliases and hashes in one request. This means we don't
    have to track as complex of data.

    Parameters
    ----------
    config
        The prepuller configuration, used to determine the Docker registry and
        repository, and which tags should be prepulled.
    gar
        Google Artifact Registry client.
    kubernetes
        Client to query the Kubernetes cluster for cached images.
    logger
        Logger for messages.
    """

    def __init__(
        self,
        *,
        config: PrepullerConfigGAR,
        gar: GARStorageClient,
        kubernetes: K8sStorageClient,
        logger: BoundLogger,
    ) -> None:
        super().__init__(config, kubernetes, logger)
        self._gar = gar

        # All available images.
        self._remote = RSPImageCollection([])

    def all_images_with_prepulled_status(
        self, nodes: set[str]
    ) -> list[PrepulledImage]:
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
            for i in self._remote.all_images()
        ]

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
        if reference.tag is None:
            msg = f'Docker reference "{reference}" has no tag'
            raise InvalidDockerReferenceError(msg)
        image = self._remote.image_for_tag_name(reference.tag)
        if (
            not image
            or reference.registry != self._config.gar.registry
            or reference.repository != self._config.gar.path
        ):
            msg = f'Docker reference "{reference}" not found'
            raise UnknownDockerImageError(msg)
        return image

    async def image_for_tag_name(self, tag_name: str) -> RSPImage:
        """Determine the image corresponding to a tag.

        Assume that the tag is for our configured registry and repository, and
        construct the corresponding
        `~jupyterlabcontroller.models.domain.rspimage.RSPImage`.

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
        DockerRegistryError
            Unable to retrieve the digest from the Docker Registry.
        """
        image = self._remote.image_for_tag_name(tag_name)
        if not image:
            raise UnknownDockerImageError(f"Docker tag {tag_name} not found")
        return image

    async def get_remote_images(self) -> RSPImageCollection:
        """Refresh remote images from the Google Artifact Registry.

        The collection of all remote tags is updated directly since that's
        safe, but it's not safe to update the collection of images to prepull
        until we've also checked Kubernetes to see which ones are cached.
        Otherwise, we'll think the images are missing from every node and do
        spurious prepulling. It is instead returned so that updating the
        object data can be deferred until Kubernetes data is also gathered.

        Returns
        -------
        RSPImageCollection
            New collection of images to prepull.
        """
        self._remote = await self._gar.list_images(self._config.gar)
        return self._subset_to_prepull(self._remote)

    def _subset_to_prepull(
        self, images: RSPImageCollection
    ) -> RSPImageCollection:
        """Determine the subset of remote images to prepull.

        Parameters
        ----------
        images
            All remote images.

        Returns
        -------
        RSPImageCollection
            The subset of images that our configuration says we should
            prepull.
        """
        include = {self._config.recommended_tag}
        if self._config.pin:
            include.update(self._config.pin)
        return images.subset(
            releases=self._config.num_releases,
            weeklies=self._config.num_weeklies,
            dailies=self._config.num_dailies,
            include=include,
        )
