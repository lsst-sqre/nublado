"""Tag manipulation methods to allow deduplication/consolidation of images
"""


from copy import copy
from typing import List, Optional

from structlog.stdlib import BoundLogger

from ...models.domain.prepuller import (
    DigestToNodeTagImages,
    NodeContainers,
    NodeTagImage,
)
from ...models.tag import RSPTag, RSPTagList, RSPTagType, StandaloneRSPTag
from ...models.v1.prepuller import PrepullerConfiguration
from ...storage.k8s import ContainerImage
from .state import PrepullerState
from .util import extract_path_from_image_ref


class PrepullerTagClient:
    def __init__(
        self,
        state: PrepullerState,
        logger: BoundLogger,
        config: PrepullerConfiguration,
    ) -> None:
        self.state = state
        self.logger = logger
        self.config = config

    def get_current_image_state(
        self, images_by_node: NodeContainers
    ) -> List[NodeTagImage]:
        # This is a convenience method, used by PrepullerK8sClient,
        # that uses the rest of our methods as a processing pipeline.

        # First, get_tags_from_images converts images to the rich RSPTag
        # format
        tags = self.get_tags_from_images(images_by_node)

        # Second, the cycle filter, if any, is applied
        cycletags = self.filter_tags_by_cycle(tags)

        # Finally, deduplicate the tags and return NodeTagImages
        node_images = self.deduplicate_images_from_tags(cycletags)

        return node_images

    def get_tags_from_images(self, nc: NodeContainers) -> List[RSPTag]:
        """Take a set of NodeContainers and return a list of RSPTags
        corresponding to all images on them.  This list will contain
        duplicates.
        """
        r: List[RSPTag] = list()
        for node in nc:
            ctrs = nc[node]
            for ctr in ctrs:
                t = self.make_tags_from_ctr(ctr, node)
                r.extend(t)
        return r

    def make_tags_from_ctr(
        self,
        ctr: ContainerImage,
        node: str,
    ) -> List[RSPTag]:
        """Take a ContainerImage and return a list of RSPTags that correspond
        to that image."""
        digest = ""
        for c in ctr.names:
            # Extract the digest, making sure we don't have conflicting
            # digests.
            if "@sha256:" in c:
                _nd = c.split("@")[-1]
                if not digest:
                    digest = _nd
                if digest != _nd:
                    raise RuntimeError(f"{c} has multiple digests")
        r: List[RSPTag] = list()
        for c in ctr.names:
            # Start over and do it with tags.  Skip the digest.
            # That does mean there's no way to get untagged images out of
            # the config unless it's a pin.
            if "@sha256:" in c:
                continue
            tag = c.split(":")[-1]
            if self.config.alias_tags is None:
                raise RuntimeError("Alias tags is none")
            config_aliases = self.config.alias_tags
            partial = StandaloneRSPTag.parse_tag(tag=tag)
            if partial.display_name == tag:
                partial.display_name = StandaloneRSPTag.prettify_tag(tag=tag)
            tagobj = RSPTag(
                tag=tag,
                image_ref=c,
                digest=digest,
                alias_tags=config_aliases,
                image_type=partial.image_type,
                display_name=partial.display_name,
                semantic_version=partial.semantic_version,
                cycle=partial.cycle,
                size=ctr.size_bytes,
                nodes=[node],
            )
            r.append(tagobj)
        return r

    def filter_tags_by_cycle(self, tags: List[RSPTag]) -> List[RSPTag]:
        """If there is a cycle, restrict our tags to it.  Used at T&S
        installations to ensure correct XML.
        """
        if self.config.cycle is None:
            return tags
        return [t for t in tags if t.cycle == self.config.cycle]

    # This all is doing way too much work, and a lot of that is because I'm
    # reusing the Tag class from cachemachine, which isn't quite the right
    # paradigm for Nublado v3.
    #
    # Nevertheless, this is a FIXME later: All of this work is in-memory,
    # so the time it takes is going to be dwarfed by our actual querying-
    # the-control-plane network I/O, and even if we have a few hundred tags
    # per image, we're talking maybe dozens of megabytes at most, which
    # really ain't much in this day and age.
    #
    # Note that this method also calls consolidate_tags()
    def deduplicate_images_from_tags(
        self,
        tags: List[RSPTag],
    ) -> List[NodeTagImage]:
        dmap: DigestToNodeTagImages = dict()
        for tag in tags:
            digest = tag.digest
            if digest is None or digest == "":
                # This is completely normal; only one pseudo-tag is going to
                # have a digest.
                continue
            img = NodeTagImage(
                path=extract_path_from_image_ref(ref=tag.image_ref),
                digest=digest,
                name=tag.display_name,
                size=tag.size,
                nodes=copy(tag.nodes),
                known_alias_tags=copy(tag.alias_tags),
                tags={tag.tag: tag.display_name},
                prepulled=False,
            )

            if digest not in dmap:
                dmap[digest] = img
            else:
                extant_image = dmap[digest]
                if img.path != extant_image.path:
                    self.logger.warning(
                        f"Image {digest} found as {img.path} "
                        + f"and also {extant_image.path}."
                    )
                    continue
                extant_image.tags.update(img.tags)
                for t in tag.nodes:
                    if t not in extant_image.nodes:
                        extant_image.nodes.append(t)
                if tag.alias_tags is not None:
                    for alias in tag.alias_tags:
                        if alias not in extant_image.known_alias_tags:
                            extant_image.known_alias_tags.append(alias)
        for digest in dmap:
            self.consolidate_tags(dmap[digest])
        return list(dmap.values())

    def consolidate_tags(self, img: NodeTagImage) -> NodeTagImage:
        """We have an annotated image with many tags.  We want to work
        through these tags and return an image with a canonical pull tag
        and a single, but possibly compound, (e.g.
        "Recommended (Weekly 2022_44)") display name.
        """

        recommended = self.config.recommended_tag
        primary_tag = ""
        primary_name = ""
        other_names: List[str] = list()
        best_tag_type: Optional[RSPTagType] = None
        best_nonalias_tag_type: Optional[RSPTagType] = None

        if recommended in img.tags:
            primary_tag = recommended
            primary_name = img.tags[recommended]
            img.all_tags.append(recommended)

        img.tagobjs = RSPTagList()
        img.tagobjs.all_tags = list()
        for t in img.tags:
            # Turn each text tag into a stripped-down RSPTag...
            img.tagobjs.all_tags.append(
                RSPTag.from_tag(
                    t, digest=img.digest, alias_tags=img.known_alias_tags
                )
            )
        # And then sort them.
        img.tagobjs.sort_all_tags()

        # Now that they're sorted, construct the return image with
        # a compound display_name, a canonical tag, and a favored
        # image type.
        for t_obj in img.tagobjs.all_tags:
            if primary_name == "":
                primary_name = t_obj.display_name
                primary_tag = t_obj.tag
            else:
                other_names.append(t_obj.display_name)
            if best_tag_type is None:
                best_tag_type = t_obj.image_type
            if (
                best_nonalias_tag_type is None
                and t_obj.image_type != RSPTagType.ALIAS
            ):
                best_nonalias_tag_type = t_obj.image_type
        tag_description: str = primary_name
        if other_names:
            tag_description += f" ({', '.join(x for x in other_names)})"
        # The "best" tag is the one corresponding to the highest-sorted
        # tag.  all_tags will be sorted according to the tagobjs, which is
        # to say, according to type.
        # And we know the digest, so, hey, let's make that part of the pull
        # path!
        untagged = img.path.split(":")[0]
        path = f"{untagged}:{primary_tag}@{img.digest}"
        return NodeTagImage(
            path=path,
            name=tag_description,
            digest=img.digest,
            tags=copy(img.tags),
            size=img.size,
            prepulled=img.prepulled,
            best_tag=primary_tag,
            all_tags=[t.tag for t in img.tagobjs.all_tags],
            nodes=copy(img.nodes),
            known_alias_tags=copy(img.known_alias_tags),
            tagobjs=copy(img.tagobjs),
            best_tag_type=best_tag_type,
            best_nonalias_tag_type=best_nonalias_tag_type,
        )
