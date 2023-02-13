"""Classes to hold all the semantic data and metadata we can extract from a
tag.  Mostly simplified from cachemachine's implementation.

These are specific to the Rubin Science Platform tag conventions.  The tag
must be in the format specified by https://sqr-059.lsst.io"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Self

from .domain.rsptag import RSPImageTag, RSPImageType
from .v1.prepuller import Image


@dataclass
class RSPTag(RSPImageTag):
    """The primary method of RSPTag construction
    is the from_tag classmethod.  The RSPTag holds all the metadata
    encoded within a particular tag (in its base class) and also additional
    metadata known and/or calculated via outside sources: the
    image digest, whether the tag is a known alias, and the image reference.
    """

    image_ref: str
    """This is the Docker reference for this particular image.  It's not
    actually used within this class, but it's useful as general image
    metadata, since it's required to pull the image.

    example: index.docker.io/lsstsqre/sciplat-lab:w_2021_22
    """

    digest: str
    """Image digest for a particular image.  It is required, because without
    it, you might as well use a StandaloneRSPTag.

    example: ("sha256:419c4b7e14603711b25fa9e0569460a753"
              "c4b2449fe275bb5f89743b01794a30")
    """

    size: Optional[int]
    """Size in bytes for a particular image.  ``None`` if unknown.
    """

    alias_tags: List[str]
    """List of known aliases for this tag.
    """

    nodes: List[str]
    """List of names of nodes to which the image corresponding to the tag
    is pulled.
    """

    # We use a classmethod here rather than just allowing specification of
    # the fields because we generally want to derive most of our attributes.
    @classmethod
    def from_tag(
        cls,
        tag: str,
        digest: str,
        image_ref: str = "",
        alias_tags: List[str] = list(),
        nodes: List[str] = list(),
        override_name: str = "",
        override_cycle: Optional[int] = None,
        size: Optional[int] = None,
    ) -> Self:
        """Create a RSPTag object from a tag and a list of alias tags.
        Allow overriding name rather than generating one, and allow an
        optional digest parameter."""
        if not digest:
            raise RuntimeError("A digest is required to create an RSPTag")
        partial_tag = RSPImageTag.from_str(tag)
        image_type = partial_tag.image_type
        display_name = partial_tag.display_name
        cycle = partial_tag.cycle
        # Here's where we glue in the alias knowledge.  Note that we just
        # special-case "latest" and "latest_<anything>"
        if tag in alias_tags or tag == "latest" or tag.startswith("latest_"):
            image_type = RSPImageType.ALIAS
            display_name = tag.replace("_", " ").title()
        # And here we override the name if appropriate.
        if override_name:
            display_name = override_name
        # Override cycle if appropriate
        if override_cycle:
            cycle = override_cycle
        return cls(
            tag=tag,
            image_ref=image_ref,
            digest=digest,
            size=size,
            image_type=image_type,
            display_name=display_name,
            version=partial_tag.version,
            cycle=cycle,
            alias_tags=alias_tags,
            nodes=nodes,
        )

    def is_recognized(self) -> bool:
        """Only return true if the image is a known type that is not known
        to be an alias.  It's possible that we also want to exclude
        experimental images.
        """
        img_type = self.image_type
        unrecognized = (RSPImageType.UNKNOWN, RSPImageType.ALIAS)
        if img_type in unrecognized:
            return False
        return True


# Below here, we have some convenience classes to produce sorted lists
# and dicts mapping tag names or digests to RSPTag objects.


@dataclass
class TagMap:
    by_digest: Dict[str, List[RSPTag]]
    by_tag: Dict[str, RSPTag]


class RSPTagList:
    """This is a class to hold tag objects and keep them sorted.  It can
    yield TagMaps on demand
    """

    def __init__(self, tags: List[RSPTag]) -> None:
        self._all_tags: List[RSPTag] = list()
        self._tag_map: TagMap = TagMap(by_digest=dict(), by_tag=dict())
        self._rebuild(tags=tags)

    @property
    def tags(self) -> List[RSPTag]:
        return self._all_tags

    @property
    def tag_map(self) -> TagMap:
        return self._tag_map

    def set_tags(self, tags: List[RSPTag]) -> None:
        self._rebuild(tags)

    def _rebuild(self, tags: List[RSPTag]) -> None:
        self._all_tags = tags
        self._sort_all_tags()
        self._make_tag_map()

    def _sort_all_tags(self) -> None:
        new_tags = []
        for image_type in RSPImageType:
            tags = (t for t in self._all_tags if t.image_type == image_type)
            new_tags.extend(sorted(tags, reverse=True))
        self._all_tags = new_tags

    def to_imagelist(self) -> List[Image]:
        image_list: List[Image] = list()
        for t in self.tags:
            image_list.append(
                Image(
                    path=f"{t.image_ref}@{t.digest}",
                    digest=t.digest,
                    name=t.display_name,
                    tags={t.tag: t.display_name},
                )
            )
        return image_list

    def _by_digest(self) -> Dict[str, List[RSPTag]]:
        digestmap: Dict[str, List[RSPTag]] = dict()
        for tag in self.tags:
            if tag.digest not in digestmap:
                digestmap[tag.digest] = list()
            digestmap[tag.digest].append(tag)
        return digestmap

    def _by_tag(self) -> Dict[str, RSPTag]:
        tagdict: Dict[str, RSPTag] = dict()
        for tag in self.tags:
            tagdict[tag.tag] = tag
        return tagdict

    def _make_tag_map(self) -> None:
        self._tag_map = TagMap(
            by_digest=self._by_digest(), by_tag=self._by_tag()
        )

    def __str__(self) -> str:
        value = f"{type(self).__name__}: by_digest: {self._by_digest()}"
        value += f" ; by_tag: {self._by_tag()}"
        return value
