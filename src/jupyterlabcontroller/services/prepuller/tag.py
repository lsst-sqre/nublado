"""Tag manipulation methods to allow deduplication/consolidation of images
"""


from copy import copy
from typing import List, Optional

from structlog.stdlib import BoundLogger

from ...exceptions import StateUpdateError
from ...models.domain.prepuller import (
    DigestToNodeTagImages,
    NodeContainers,
    NodeTagImage,
)
from ...models.domain.rsptag import RSPImageType
from ...models.tag import RSPTag, RSPTagList
from ...models.v1.prepuller import PrepullerConfiguration
from ...storage.k8s import ContainerImage
from .state import PrepullerState


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

    def get_local_images_by_digest(
        self, images_by_node: NodeContainers
    ) -> DigestToNodeTagImages:
        # This is a convenience method, used by PrepullerK8sClient,
        # that uses the rest of our methods as a processing pipeline.

        # First, get_tags_from_images converts images to the rich RSPTag
        # format
        tags = self.get_tags_from_images(images_by_node)

        # Second, the cycle filter, if any, is applied
        cycletags = self.filter_tags_by_cycle(tags)

        # Finally, deduplicate the tags and return DigestToNodeTagImages
        node_images = self.images_by_digest(cycletags)
        return node_images

    def get_current_image_state(
        self, images_by_node: NodeContainers
    ) -> List[NodeTagImage]:
        node_images = self.get_local_images_by_digest(images_by_node)
        return list(node_images.values())

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
                    self.logger.error(
                        f"{c} has multiple digests.  Keeping {digest} "
                        f"and ignoring {_nd}.  Check repository integrity"
                    )
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
            tagobj = RSPTag.from_tag(
                tag=tag,
                image_ref=c,
                digest=digest,
                alias_tags=self.config.alias_tags,
                nodes=[node],
                size=ctr.size_bytes,
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
    def images_by_digest(
        self,
        tags: List[RSPTag],
    ) -> DigestToNodeTagImages:
        dmap: DigestToNodeTagImages = dict()
        for tag in tags:
            digest = tag.digest
            if digest is None or digest == "":
                # This is completely normal; only one pseudo-tag is going to
                # have a digest.
                continue
            img = NodeTagImage(
                path=tag.image_ref,
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
                    self.logger.info(
                        f"Image {digest} found as {img.path} "
                        + f"and also {extant_image.path}."
                    )
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
        return dmap

    def deduplicate_images_from_tags(
        self, tags_by_digest: DigestToNodeTagImages
    ) -> List[NodeTagImage]:
        return list(tags_by_digest.values())

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
        best_tag_type: Optional[RSPImageType] = None
        best_nonalias_tag_type: Optional[RSPImageType] = None

        savedigest = ""
        if recommended in img.tags:
            primary_tag = recommended
            primary_name = img.tags[recommended]
            img.all_tags.append(recommended)
            img.known_alias_tags.append(recommended)
            best_tag_type = RSPImageType.ALIAS
        tag_objs: List[RSPTag] = list()
        for t in img.tags:
            # Turn each text tag into a stripped-down RSPTag...
            tag_objs.append(
                RSPTag.from_tag(
                    tag=t,
                    digest=img.digest,
                    alias_tags=img.known_alias_tags,
                    image_ref=img.path,  # Maybe?
                )
            )
        # And then put those tags into the RSPTagList, which will sort it
        # for us and allow us to retrieve a TagMap.
        img.tagobjs = RSPTagList(tags=tag_objs)

        # Now that they're sorted, construct the return image with
        # a compound display_name, a canonical tag, and a favored
        # image type.

        tags_by_digest = img.tagobjs.tag_map.by_digest
        for digest in tags_by_digest:
            tag_objs = tags_by_digest[digest]
            if len(tag_objs) > 1:
                savedigest = digest
                for t_obj in tag_objs:
                    # The construction loses the fact that recommended is
                    # inherently an alias.  Add that back in.
                    if (
                        t_obj.image_type == RSPImageType.UNKNOWN
                        and t_obj.tag == recommended
                    ):
                        t_obj.image_type = RSPImageType.ALIAS
                    if primary_name == "":
                        primary_name = t_obj.display_name
                        primary_tag = t_obj.tag
                    else:
                        other_names.append(t_obj.display_name)
                    if best_tag_type is None:
                        best_tag_type = t_obj.image_type
                    if (
                        best_nonalias_tag_type is None
                        and t_obj.image_type != RSPImageType.ALIAS
                    ):
                        best_nonalias_tag_type = t_obj.image_type
            else:
                only_tag = img.tagobjs.tags[0]
                primary_name = only_tag.display_name
                primary_tag = only_tag.tag
        tag_desc: str = primary_name
        if other_names:
            if primary_name in other_names:
                other_names.remove(primary_name)
                if other_names:
                    tag_desc += f" ({', '.join(x for x in other_names)})"
        if tag_desc != primary_name:
            # Change it for reporting of remote images too.
            self.logger.info(f"Updating name for {savedigest} -> {tag_desc}")
            try:
                self.state.update_remote_image_name_by_digest(
                    savedigest, tag_desc
                )
            except StateUpdateError as exc:
                self.logger.error(f"Name update failed: {exc}")
        # The "best" tag is the one corresponding to the highest-sorted
        # tag.  all_tags will be sorted according to the tagobjs, which is
        # to say, according to type.
        # And we know the digest, so, hey, let's make that part of the pull
        # path!
        untagged = img.path.split(":")[0]
        path = f"{untagged}:{primary_tag}@{img.digest}"
        # and now that we've done all *that*...if we have the tag in our
        # remote images by digest, which we should, we update that image's
        # display name.
        return NodeTagImage(
            path=path,
            name=tag_desc,
            digest=img.digest,
            tags=copy(img.tags),
            size=img.size,
            prepulled=img.prepulled,
            best_tag=primary_tag,
            all_tags=[t.tag for t in img.tagobjs.tags],
            nodes=copy(img.nodes),
            known_alias_tags=copy(img.known_alias_tags),
            tagobjs=copy(img.tagobjs),
            best_tag_type=best_tag_type,
            best_nonalias_tag_type=best_nonalias_tag_type,
        )
