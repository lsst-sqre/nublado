"""Image source using a Docker Registry."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from structlog.stdlib import BoundLogger

from ...exceptions import InvalidDockerReferenceError, UnknownDockerImageError
from ...models.domain.docker import DockerReference
from ...models.domain.form import MenuImage
from ...models.domain.kubernetes import KubernetesNodeImage
from ...models.domain.rspimage import RSPImage, RSPImageCollection
from ...models.domain.rsptag import RSPImageTagCollection
from ...models.v1.prepuller import PrepulledImage
from ...models.v1.prepuller_config import DockerSourceConfig, PrepullerConfig
from ...storage.docker import DockerStorageClient
from .base import ImageSource

__all__ = ["DockerImageSource"]


class DockerImageSource(ImageSource):
    """Image source using a Docker Registry.

    Docker has a very awkward API that makes it expensive to get the hash of
    an image or to see which tags alias each other. The Docker specialization
    of the `DockerImageSource` therefore has to juggle both tag collections
    (all known tags, possibly without hashes) and image collections (images
    fully resolved with tags).

    Parameters
    ----------
    config
        Source configuration specifying the Docker registry and repository.
    docker
        Client to query the Docker API for tags.
    logger
        Logger for messages.
    """

    def __init__(
        self,
        config: DockerSourceConfig,
        docker: DockerStorageClient,
        logger: BoundLogger,
    ) -> None:
        super().__init__(logger)
        self._config = config
        self._docker = docker

        # All tags present in the registry and repository per its API.
        self._tags = RSPImageTagCollection([])

        # Tags that have been resolved to images.
        self._images = RSPImageCollection([])

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
            Docker reference, which may or may not have a known digest.

        Returns
        -------
        RSPImage
            Corresponding image.

        Raises
        ------
        DockerRegistryError
            Raised if retrieving the digest from the Docker Registry failed.
        InvalidDockerReferenceError
            Raised if the Docker reference doesn't contain a tag. References
            without a tag are valid references to Docker, but for our purposes
            we always want to have a tag to use for debugging, status display
            inside the lab, etc.
        UnknownDockerImageError
            Raised if this is not one of the remote images we know about.
        """
        if (
            reference.registry != self._config.registry
            or reference.repository != self._config.repository
        ):
            msg = f'Docker reference "{reference}" not found'
            raise UnknownDockerImageError(msg)

        # See if we already have an image for this digest.
        if reference.digest:
            image = self._images.image_for_digest(reference.digest)
            if image:
                return image

        # From this point forward, we're going to retrieve by tag so we need a
        # valid tag.
        if reference.tag is None:
            msg = f'Docker reference "{reference}" has no tag'
            raise InvalidDockerReferenceError(msg)

        # See if we have an image for this tag.
        image = self._images.image_for_tag_name(reference.tag)
        if image:
            return image

        # Otherwise, retrieve the RSPImageTag for the image to ensure that it
        # was in the list of available remote images.
        tag = self._tags.tag_for_tag_name(reference.tag)
        if not tag:
            msg = f'Docker reference "{reference}" not found'
            raise UnknownDockerImageError(msg)

        # We found the tag and can resolve this reference to an RSPImage.
        if reference.digest:
            digest = reference.digest
        else:
            digest = await self._docker.get_image_digest(
                self._config, reference.tag
            )
        return RSPImage.from_tag(
            registry=self._config.registry,
            repository=self._config.repository,
            tag=tag,
            digest=digest,
        )

    async def image_for_tag_name(self, tag_name: str) -> RSPImage:
        """Determine the image corresponding to a tag.

        Assuming that the tag is for our image source, construct the
        corresponding `~jupyterlabcontroller.models.domain.rspimage.RSPImage`.

        Parameters
        ----------
        tag_name
            Tag of the image

        Returns
        -------
        RSPImage
            Corresponding image.

        Raises
        ------
        UnknownDockerImageError
            The requested tag is not found.
        DockerRegistryError
            Unable to retrieve the digest from the Docker Registry.
        """
        image = self._images.image_for_tag_name(tag_name)
        if image:
            return image
        tag = self._tags.tag_for_tag_name(tag_name)
        if not tag:
            raise UnknownDockerImageError(f'Docker tag "{tag_name}" not found')
        digest = await self._docker.get_image_digest(self._config, tag_name)
        return RSPImage.from_tag(
            registry=self._config.registry,
            repository=self._config.repository,
            tag=tag,
            digest=digest,
        )

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

    def menu_images(self) -> list[MenuImage]:
        """All known images suitable for display in the spawner menu.

        Include a full reference with a digest if we have one available.
        Otherwise, just include the tag.

        Returns
        -------
        list of MenuImage
            All known images.
        """
        registry = self._config.registry
        repository = self._config.repository
        menu_images = []
        for tag in self._tags.all_tags():
            image = self._images.image_for_tag_name(tag.tag)
            if image:
                reference = image.reference_with_digest
                menu_image = MenuImage(reference, image.display_name)
            else:
                reference = f"{registry}/{repository}:{tag.tag}"
                menu_image = MenuImage(reference, tag.display_name)
            menu_images.append(menu_image)
        return menu_images

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
        registry = self._config.registry
        repository = self._config.repository
        prepulled_images = []
        for tag in self._tags.all_tags():
            image = self._images.image_for_tag_name(tag.tag)
            if image:
                prepulled_image = PrepulledImage.from_rsp_image(image, nodes)
            else:
                prepulled_image = PrepulledImage(
                    reference=f"{registry}/{repository}:{tag.tag}",
                    tag=tag.tag,
                    name=tag.display_name,
                    prepulled=False,
                )
            prepulled_images.append(prepulled_image)
        return prepulled_images

    async def update_images(
        self,
        prepull: PrepullerConfig,
        node_cache: Mapping[str, list[KubernetesNodeImage]],
    ) -> RSPImageCollection:
        """Update image information and determine what images to prepull.

        Refresh remote tags and images from the Docker registry, find the
        subset that we're prepulling, and convert those to images. Resolve
        aliases and match those with the cached images on nodes to update node
        presence information.

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

        Notes
        -----
        Getting an image for a tag is an expensive operation, requiring a
        ``HEAD`` call to the Docker API for each image, so we only want to do
        this for images we care about, namely the images that we're going to
        prepull.

        The digest is retrieved again on each refresh because it may have
        changed (Docker registry tags are not immutable).
        """
        tags = await self._docker.list_tags(self._config)
        aliases = {prepull.recommended_tag} | set(prepull.alias_tags)
        self._tags = RSPImageTagCollection.from_tag_names(
            tags, aliases, prepull.cycle
        )

        # Get digests for the prepulled images in parallel.
        to_prepull = self._subset_to_prepull(self._tags, prepull)
        tasks = [
            asyncio.create_task(
                self._docker.get_image_digest(self._config, tag.tag)
            )
            for tag in to_prepull.all_tags()
        ]
        digests = await asyncio.gather(*tasks)

        # Construct the images.
        images = []
        for tag, digest in zip(to_prepull.all_tags(), digests):
            image = RSPImage.from_tag(
                registry=self._config.registry,
                repository=self._config.repository,
                tag=tag,
                digest=digest,
            )
            images.append(image)
        image_collection = RSPImageCollection(images)

        # Set their node presence information.
        for node, node_images in node_cache.items():
            for node_image in node_images:
                if not node_image.digest:
                    continue
                image_collection.mark_image_seen_on_node(
                    node_image.digest, node, node_image.size
                )

        # Store and return the results.
        self._images = image_collection
        return image_collection

    def _subset_to_prepull(
        self, tags: RSPImageTagCollection, prepull: PrepullerConfig
    ) -> RSPImageTagCollection:
        """Determine the subset of remote images to prepull.

        Parameters
        ----------
        tags
            All remote images.
        config
            Configuration of images to prepull.

        Returns
        -------
        RSPImageTagCollection
            The subset of images that our configuration says we should
            prepull.
        """
        include = {prepull.recommended_tag}
        if prepull.pin:
            include.update(prepull.pin)
        return tags.subset(
            releases=prepull.num_releases,
            weeklies=prepull.num_weeklies,
            dailies=prepull.num_dailies,
            include=include,
        )
