"""Abstract data types for handling RSP images."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field
from typing import Self

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

    size: int | None = None
    """Size of the image in bytes if known."""

    aliases: set[str] = field(default_factory=set)
    """Known aliases for this image.

    This may include other alias tags that all resolve to the same underlying
    image, other non-alias tags with the same digest, and aliases that are not
    present in the same collection. It is intended primarily for the use of
    `RSPImageCollection`, which contains more sophisticated alias tracking
    logic that is aware of the contents of the collection.
    """

    alias_target: str | None = None
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
        for alias in target.aliases:
            if alias != self.tag:
                self.aliases.add(alias)
        target.aliases.add(self.tag)
        self.cycle = target.cycle

        # If the tag display name has cycle information, we don't want to keep
        # that part when adding the description of the target tag since it
        # will duplicate the cycle information in the target tag. We know how
        # tag display names are constructed and know we can safely discard the
        # parenthetical, so do that and otherwise keep the cycle-aware display
        # name parsing done in the RSPImageTag alias method.
        if " (" in self.display_name:
            cutoff = self.display_name.index(" (")
            base_display_name = self.display_name[:cutoff].title()
        else:
            base_display_name = self.tag.replace("_", " ").title()

        # If the target has a SAL cycle, it already has parentheses in its
        # description. Nested parentheses are ugly, so convert that to another
        # comma-separated stanza.
        if " (" in target.display_name:
            extra = target.display_name.replace(" (", ", ").replace(")", "")
        else:
            extra = target.display_name
        self.display_name = f"{base_display_name} ({extra})"


class RSPImageCollection:
    """Provides operations on a collection of `RSPImage` objects.

    Parameters
    ----------
    images
        `RSPImage` objects to store.
    cycle
        If given, only add images with a matching cycle.
    """

    def __init__(
        self, images: Iterable[RSPImage], cycle: int | None = None
    ) -> None:
        self._by_digest: dict[str, RSPImage]
        self._by_tag_name: dict[str, RSPImage]
        self._by_type: defaultdict[RSPImageType, list[RSPImage]]

        # Unresolved aliases by digest that are not in _by_digest.
        self._unresolved_aliases: defaultdict[str, list[RSPImage]]

        # Ingest all images.
        self._replace_contents(images, cycle)

    def add(self, image: RSPImage) -> None:
        """Add an image to the collection.

        If this has the same digest as an image already in the collection, the
        newly added image will replace the old one for `image_for_digest`
        purposes.

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
        if image.digest in self._by_digest:
            other = self._by_digest[image.digest]
            self._resolve_duplicate(image, other)
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
            If `True`, hide images that are the primary target of an alias
            tag in the same collection. This is used for menu generation to
            suppress a duplicate entry for an image that already appeared
            earlier in the menu under an alias. We do not suppress images
            with the same digest that are aliased by the alias tag but are
            not its primary target, on the somewhat tenuous grounds that the
            description of the alias will not mention that image and it may
            seem strange for it to go missing.
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
                if hide_aliased and self._is_image_aliased(image):
                    continue
                if hide_resolved_aliases and image.alias_target:
                    if image.alias_target in self._by_tag_name:
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

    def mark_image_seen_on_node(
        self, digest: str, node: str, image_size: int | None = None
    ) -> None:
        """Mark an image as seen on a node.

        This is implemented by the image collection so that we can update all
        of the image's aliases as well.

        Parameters
        ----------
        digest
            Digest of image seen.
        node
            Name of the node the image was seen on.
        image_size
            If given, the observed image size, used to update the images.
        """
        if digest not in self._by_digest:
            return
        image = self._by_digest[digest]
        image.nodes.add(node)
        if image_size:
            image.size = image_size
        for alias in image.aliases:
            if alias not in self._by_tag_name:
                continue
            other = self._by_tag_name[alias]
            other.nodes.add(node)
            if image_size:
                other.size = image_size

    def subset(
        self,
        *,
        releases: int = 0,
        weeklies: int = 0,
        dailies: int = 0,
        include: set[str] | None = None,
    ) -> RSPImageCollection:
        """Return a subset of the image collection.

        Parameters
        ----------
        releases
            Number of releases to include.
        weeklies
            Number of weeklies to include.
        dailies
            Number of dailies to include.
        include
            Include this list of tags even if they don't meet other criteria.

        Returns
        -------
        RSPImageCollection
            The desired subset.
        """
        images = []

        # Extract the desired image types.
        if releases and RSPImageType.RELEASE in self._by_type:
            images.extend(self._by_type[RSPImageType.RELEASE][0:releases])
        if weeklies and RSPImageType.WEEKLY in self._by_type:
            images.extend(self._by_type[RSPImageType.WEEKLY][0:weeklies])
        if dailies and RSPImageType.DAILY in self._by_type:
            images.extend(self._by_type[RSPImageType.DAILY][0:dailies])

        # Include additional images if they're present in the collection.
        if include:
            for tag in include:
                if tag in self._by_tag_name:
                    images.append(self._by_tag_name[tag])

        # Return the results.
        return RSPImageCollection(images)

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

    def _is_image_aliased(self, image: RSPImage) -> bool:
        """Return whether this image is aliased.

        An image is aliased if and only if it is not itself an image of alias
        type, one of its aliases is an image of alias type, that image is in
        the same collection, and that image's alias target points to this
        image.

        Returns
        -------
        bool
            Whether the image is an alias.
        """
        if image.image_type == RSPImageType.ALIAS:
            return False
        for alias in image.aliases:
            alias_image = self._by_tag_name.get(alias)
            if not alias_image:
                continue
            if alias_image.image_type != RSPImageType.ALIAS:
                continue
            if alias_image.alias_target == image.tag:
                return True
        return False

    def _replace_contents(
        self, images: Iterable[RSPImage], cycle: int | None = None
    ) -> None:
        """Replace the contents of the collection with the provided images.

        This is primarily used by the constructor, but may also be used to
        reindex the entire collection if needed.

        Parameters
        ----------
        images
            All images in the collection. Existing images will be discarded.
        cycle
            If given, only add images with a matching cycle.
        """
        self._by_digest = {}
        self._by_tag_name = {}
        self._by_type = defaultdict(list)
        self._unresolved_aliases = defaultdict(list)

        # First pass: store all images by tag name, and all images other than
        # unresolved images by digest. If there is a conflict between two
        # non-alias images, the first one added wins on the theory that
        # hopefully the Docker image source API returns the newest images
        # first.
        unresolved = []
        for image in images:
            if cycle is not None and image.cycle != cycle:
                continue
            self._by_tag_name[image.tag] = image
            if image.is_possible_alias:
                unresolved.append(image)
            elif image.digest in self._by_digest:
                other = self._by_digest[image.digest]
                self._resolve_duplicate(other, image)
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
                self._resolve_duplicate(image, other)
            else:
                self._unresolved_aliases[image.digest].append(image)
                self._by_digest[image.digest] = image

        # Now, all images have been resolved where possible. Take a third
        # pass and register all images by type.
        for image in images:
            if cycle is not None and image.cycle != cycle:
                continue
            self._by_type[image.image_type].append(image)

        # Sort all of the images by reverse order so the newest are first.
        # This allows all_images to return sorted order efficiently.
        for image_list in self._by_type.values():
            image_list.sort(reverse=True)

    def _resolve_duplicate(self, new: RSPImage, old: RSPImage) -> None:
        """Handle images with the same digest.

        Implements the following logic:

        #. If both images are possible aliases, mark them as aliases of each
           other and add ``new`` to the list of possible aliases.
        #. If ``new`` is a possible alias and ``old`` is not, resolve ``new``
           as an alias of ``old`` and add ``new`` as an alias of all of the
           aliases of ``old``.
        #. If neither ``new`` nor ``old`` are possible aliases, replace
           ``old`` with ``new`` in ``_by_digest``, change any aliases that
           point to ``old`` to point to ``new`` instead, and add ``new`` as
           an alias to all of the aliases of ``old``, as well as marking them
           as aliases of each other.

        The final case, where ``old`` is a possible alias and ``new`` is not,
        is not possible by construction so is ignored. (In `add`, this case is
        handled by rebuilding the whole collection, and when building the
        collection possible aliases are always added second.)

        Parameters
        ----------
        new
            Image that will be returned from `image_for_digest` and should be
            the alias target for any alias tags.
        old
            Image that should be considered "secondary" and be recorded as a
            regular alias but not the target for alias tags. Must have the
            same digest as ``new``.
        """
        if new.digest != old.digest:
            raise RuntimeError("Resolving duplicates with differing digests")
        if new.is_possible_alias:
            if old.is_possible_alias:
                new.aliases.add(old.tag)
                old.aliases.add(new.tag)
                self._unresolved_aliases[new.digest].append(new)
            else:
                new.resolve_alias(old)
            for alias in old.aliases:
                if alias == new.tag or alias not in self._by_tag_name:
                    continue
                self._by_tag_name[alias].aliases.add(new.tag)
        else:
            new.aliases.add(old.tag)
            for alias in old.aliases:
                if alias == new.tag or alias not in self._by_tag_name:
                    continue
                new.aliases.add(alias)
                other = self._by_tag_name[alias]
                if other.alias_target == old.tag:
                    other.resolve_alias(new)
                    other.aliases.add(old.tag)
                else:
                    other.aliases.add(new.tag)
            old.aliases.add(new.tag)
            self._by_digest[new.digest] = new
