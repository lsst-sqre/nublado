"""Abstract data types for handling RSP images."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field
from typing import Optional, Self

from .rsptag import RSPImageTag, RSPImageType

__all__ = [
    "RSPImage",
    "RSPImageCollection",
]

_ALIAS_TYPES = (RSPImageType.ALIAS, RSPImageType.UNKNOWN)
"""Image types that may be aliases and can be resolved."""


@dataclass
class RSPImage(RSPImageTag):
    """A tagged Rubin Science Platform image.

    An `RSPImage` differs from a
    `~jupyterlabcontroller.models.domain.rsptag.RSPImageTag` by having a
    reference and digest, potentially additional alias tags, and possibly
    information discovered from a Kubernetes cluster, such as the image size
    and the list of nodes on which it is present.
    """

    registry: str
    """Docker registry from which this image comes."""

    repository: str
    """Docker repository from which this image comes."""

    digest: str
    """Image digest for the image, including prefixes like ``sha256:``."""

    size: Optional[int] = None
    """Size of the image in bytes if known."""

    aliases: set[str] = field(default_factory=set)
    """Known aliases for this image."""

    alias_target: Optional[str] = None
    """The tag of the image for which this is an alias, if known."""

    nodes: set[str] = field(default_factory=set)
    """Names of nodes on which this image is present."""

    @classmethod
    def from_tag(
        cls, *, registry: str, repository: str, tag: RSPImageTag, digest: str
    ) -> Self:
        """Construct an image from an existing tag.

        Parameters
        ----------
        registry
            Docker registry for this image.
        repository
            Docker repository for this image.
        tag
            Tag for this image.
        digest
            Digest for this image.

        Returns
        -------
        RSPImage
            Resulting image object.
        """
        return cls(
            registry=registry,
            repository=repository,
            digest=digest,
            **asdict(tag),
        )

    @property
    def is_possible_alias(self) -> bool:
        """Whether this tag could be an alias."""
        return self.image_type in _ALIAS_TYPES

    @property
    def reference(self) -> str:
        """Docker reference for this image."""
        return f"{self.registry}/{self.repository}:{self.tag}"

    @property
    def reference_with_digest(self) -> str:
        """Docker reference for this image, with the digest."""
        return f"{self.registry}/{self.repository}:{self.tag}@{self.digest}"

    def resolve_alias(self, target: RSPImage) -> None:
        """Resolve an alias tag with information about its target.

        If we discover the target tag of an alias tag, we can improve the
        alias tag's display name and cycle information using the information
        of the underlying tag. This normally happens when ingesting a set of
        images, including alias images, into an `RSPImageCollection`.

        If the tag was previously an unknown tag but we found another tag with
        the same digest, assume it is an alias tag and upgrade it.

        Parameters
        ----------
        target
            Another tag with the same digest.

        Raises
        ------
        ValueError
            If this image has a type other than unknown or alias. (Ideally
            this should be represented in the type system, but that code is
            tedious and doesn't add much value.)
        """
        if not self.is_possible_alias:
            raise ValueError("Can only resolve alias and unknown images")
        self.image_type = RSPImageType.ALIAS
        self.alias_target = target.tag
        target.aliases.add(self.tag)
        base_display_name = self.tag.replace("_", " ").title()
        self.display_name = f"{base_display_name} ({target.display_name})"
        self.cycle = target.cycle


class RSPImageCollection:
    """Provides operations on a collection of `RSPImage` objects.

    Parameters
    ----------
    images
        `RSPImage` objects to store.
    """

    def __init__(self, images: Iterable[RSPImage]) -> None:
        self._by_digest: dict[str, RSPImage]
        self._by_tag_name: dict[str, RSPImage]
        self._by_type: defaultdict[RSPImageType, list[RSPImage]]

        # Unresolved aliases by digest that are not in _by_digest.
        self._unresolved_aliases: defaultdict[str, list[RSPImage]]

        # Ingest all images.
        self._replace_contents(images)

    def add(self, image: RSPImage) -> None:
        """Add an image to the collection.

        Parameters
        ----------
        image
            The image to add.
        """
        # If we're adding a non-alias image and we have unresolved aliases for
        # its digest, just reindex the entire collection. We otherwise have to
        # handle unknown images that are promoted to alias images and need to
        # change their sort order, which is unnecessarily complex to handle as
        # a special case.
        if not image.is_possible_alias:
            if image.digest in self._unresolved_aliases:
                all_images = list(self.all_images())
                all_images.append(image)
                self._replace_contents(all_images)
                return

        # This is a compact version of the same logic as _replace_contents.
        if image.is_possible_alias and image.digest in self._by_digest:
            other = self._by_digest[image.digest]
            if other.image_type in _ALIAS_TYPES:
                self._unresolved_aliases[image.digest].append(image)
            else:
                image.resolve_alias(other)
        else:
            self._by_digest[image.digest] = image
        self._by_tag_name[image.tag] = image
        self._by_type[image.image_type].append(image)
        self._by_type[image.image_type].sort(reverse=True)

    def all_images(
        self, hide_aliased: bool = False, hide_resolved_aliases: bool = False
    ) -> Iterator[RSPImage]:
        """All images in sorted order.

        Parameters
        ----------
        hide_aliased
            If `True`, hide images for which an alias image exists. This is
            used for menu generation to suppress a duplicate entry for an
            image that already appeared earlier in the menu under an alias.
        hide_resolved_aliases
            If `True`, hide images that are an alias for another image in the
            collection (but keep alias images when we don't have the target).
            This is used to suppress the alias images when reporting prepull
            status, where the underlying images are more useful to report.

        Returns
        -------
        list of RSPImage
            Images sorted by their type and then in reverse by their version.
        """
        for image_type in RSPImageType:
            for image in self._by_type[image_type]:
                if hide_aliased and image.aliases:
                    continue
                if hide_resolved_aliases and image.alias_target:
                    continue
                yield image

    def image_for_digest(self, digest: str) -> RSPImage | None:
        """Find an image by digest.

        Returns the non-alias image by preference, although if an alias image
        has not been resolved with a target, we may return the unresolved
        alias.

        Returns
        -------
        RSPImage or None
            The image for that digest if found, otherwise `None`.
        """
        return self._by_digest.get(digest)

    def image_for_tag_name(self, tag: str) -> RSPImage | None:
        """Find an image by tag name.

        Returns
        -------
        RSPImage or None
            The image with that tag name if found, otherwise `None`.
        """
        return self._by_tag_name.get(tag)

    def latest(self, image_type: RSPImageType) -> RSPImage | None:
        """Get the latest image of a given type.

        Parameters
        ----------
        image_type
            Image type to retrieve.

        Returns
        -------
        RSPImage or None
            Latest image of that type, if any.
        """
        images = self._by_type[image_type]
        return images[0] if images else None

    def subtract(self, other: RSPImageCollection) -> RSPImageCollection:
        """Find the list of images in this collection missing from another.

        This returns only one image per digest, preferring the non-alias
        images, since the intended use is for determining what images to
        prepull, and there's no need to prepull the same image more than once
        under different names.

        Parameters
        ----------
        other
            The other collection, whose contents will be subtracted from this
            one.

        Returns
        -------
        RSPImageCollection
            All images found in this collection that weren't in the other.
            Images are considered matching only if their digests match.
        """
        candidates = dict(self._by_digest)
        for image in other.all_images():
            if image.digest in candidates:
                del candidates[image.digest]
        return RSPImageCollection(candidates.values())

    def _replace_contents(self, images: Iterable[RSPImage]) -> None:
        """Replace the contents of the collection with the provided images.

        This is primarily used by the constructor, but may also be used to
        reindex the entire collection if needed.

        Parameters
        ----------
        images
            All images in the collection. Existing images will be discarded.
        """
        self._by_digest = {}
        self._by_tag_name = {}
        self._by_type = defaultdict(list)
        self._unresolved_aliases = defaultdict(list)

        # First pass: store all images other than unresolved images by digest.
        # If there is a conflict between two non-alias images, the last one
        # wins.  (This is for no particular reason except that it's easy.)
        unresolved = []
        for image in images:
            if image.is_possible_alias:
                unresolved.append(image)
            else:
                self._by_digest[image.digest] = image

        # Second pass: add the unresolved images now that any images they
        # alias should have been found. This is when we discover the targets
        # of alias images so that we can resolve them. Do not try to resolve
        # one alias or unknown tag with another; that adds no value. Keep
        # track of our unresolved aliases so that we can resolve them if their
        # target is added later.
        for image in unresolved:
            if image.digest in self._by_digest:
                other = self._by_digest[image.digest]
                if other.is_possible_alias:
                    self._unresolved_aliases[image.digest].append(image)
                else:
                    image.resolve_alias(other)
            else:
                self._unresolved_aliases[image.digest].append(image)
                self._by_digest[image.digest] = image

        # Now, all images have been resolved where possible. Take a second
        # pass and register all images by name and type.
        for image in images:
            self._by_tag_name[image.tag] = image
            self._by_type[image.image_type].append(image)

        # Sort all of the images by reverse order so the newest are first.
        # This allows all_images to return sorted order efficiently.
        for image_list in self._by_type.values():
            image_list.sort(reverse=True)
