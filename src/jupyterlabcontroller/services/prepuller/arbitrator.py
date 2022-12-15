"""The arbitrator reconciles cluster node state with repository node state
so that it knows what images need prepulling.
"""


from copy import copy
from typing import Any, Dict, List

from structlog.stdlib import BoundLogger

from ...models.domain.prepuller import DisplayImages, NodeTagImage
from ...models.tag import RSPTag, RSPTagType
from ...models.v1.prepuller import (
    Node,
    NodeImage,
    PrepullerConfiguration,
    PrepullerContents,
    PrepullerStatus,
    SpawnerImages,
)
from .state import PrepullerState
from .tag import PrepullerTagClient


class PrepullerArbitrator:
    def __init__(
        self,
        state: PrepullerState,
        tag_client: PrepullerTagClient,
        config: PrepullerConfiguration,
        logger: BoundLogger,
    ) -> None:

        self.state = state
        self.tag_client = tag_client
        self.logger = logger
        self.config = config

    def get_prepulls(self) -> PrepullerStatus:
        """GET /nublado/spawner/v1/prepulls"""
        # Phase 1: get prepulled status for each desired image
        node_images = self.get_images()
        # Phase 2: determine which nodes have which images
        nodes = self.get_node_cache()

        eligible_nodes = [x.name for x in nodes if x.eligible]

        # Phase 3: get desired images for menu (which are the ones to
        # prepull)
        menu_node_images = self.filter_node_images_to_desired_menu(node_images)

        prepulled: List[NodeImage] = list()
        pending: List[NodeImage] = list()

        for i_name in menu_node_images:
            img = menu_node_images[i_name]
            if img.prepulled:
                prepulled.append(
                    NodeImage(
                        path=img.path,
                        name=img.name,
                        digest=img.digest,
                        nodes=self._nodes_present(img, eligible_nodes),
                    )
                )
            else:
                pending.append(
                    NodeImage(
                        path=img.path,
                        name=img.name,
                        digest=img.digest,
                        nodes=self._nodes_present(img, eligible_nodes),
                        missing=self._nodes_missing(img, eligible_nodes),
                    )
                )
        images = PrepullerContents(prepulled=prepulled, pending=pending)
        status = PrepullerStatus(
            config=self.config, images=images, nodes=nodes
        )
        return status

    def _nodes_present(self, img: NodeTagImage, nodes: List[str]) -> List[str]:
        return [x for x in nodes if x in img.nodes]

    def _nodes_missing(self, img: NodeTagImage, nodes: List[str]) -> List[str]:
        return [x for x in nodes if x not in img.nodes]

    # Phase 1
    def get_images(self) -> List[NodeTagImage]:
        """Starting with images that are present on at least one node,
        validate their digests against the remote digests and build up
        a list of images that are
        """
        present_images = self.state.images
        remote_tags = self._make_tags_from_remote_images()
        available_remote_images = self.tag_client.deduplicate_images_from_tags(
            remote_tags
        )
        available_images = self._reconcile_local_and_remote_digests(
            present_images, available_remote_images
        )
        # Recalculate prepull status with remote images factored in
        return self.determine_image_prepull_status(available_images)

    # Phase 1A
    def _make_tags_from_remote_images(self) -> List[RSPTag]:
        # Convert our remote image digest map of Docker tags into a list of RSP
        # rich Tag format objects.  This is inefficient.  FIXME later.
        remote_images = self.state.remote_images
        available_tagobjs: List[RSPTag] = list()
        for digest in remote_images.by_digest:
            for tag in remote_images.by_digest[digest]:
                available_tagobjs.append(
                    RSPTag.from_tag(
                        tag=tag,
                        digest=digest,
                        image_ref=self.config.path,
                    )
                )
        return available_tagobjs

    # Phase 1B
    def _reconcile_local_and_remote_digests(
        self,
        local: List[NodeTagImage],
        remote: List[NodeTagImage],
    ) -> List[NodeTagImage]:
        validated_local = self._validate_digests(local, remote)
        all_img = copy(validated_local)  # Start with local images
        all_img.extend(remote)  # Add any remote images we haven't pulled
        # Rebuild our images with knowledge from remote repository
        image_map = self._rectify_images(all_img)
        # Rebuild our image list with re-consolidated tags, since we
        # might have discovered new things about the images
        return [
            self.tag_client.consolidate_tags(x) for x in image_map.values()
        ]

    # Phase 1B.i
    def _validate_digests(
        self,
        local: List[NodeTagImage],
        remote: List[NodeTagImage],
    ) -> List[NodeTagImage]:
        for local_image in local:
            if not self._validate_single_image(local_image, remote):
                # Local image has different hash than remote, so it must
                # have been retagged on the Docker repository, and therefore
                # it needs repulling, so invalidate it on all nodes.
                local_image.nodes = list()
        return local

    # Phase 1B.ii
    def _validate_single_image(
        self, l_img: NodeTagImage, remote: List[NodeTagImage]
    ) -> bool:
        for l_tag in l_img.all_tags:
            for r_img in remote:
                if l_tag in r_img.all_tags:
                    if l_img.digest != r_img.digest:
                        self.logger.warning(
                            f"Local image tag {l_tag} has digest "
                            f"{l_img.digest}, but remote image has "
                            f"digest {r_img.digest}.  Invalidating "
                            f"local image"
                        )
                        return False
        return True

    # Phase 1B.iii
    def _rectify_images(
        self, input_images: List[NodeTagImage]
    ) -> Dict[str, NodeTagImage]:
        image_map: Dict[str, NodeTagImage] = dict()
        for input_image in input_images:
            digest = input_image.digest
            if digest not in image_map:
                image_map[digest] = input_image  # We've never seen it before
            old_image = image_map[digest]  # But maybe we have.  If we just
            # added it, old_image will be the same as input_image, but if
            # not, we may need to update the image
            old_tags = set(old_image.all_tags)
            old_nodes = set(old_image.nodes)
            old_aliases = set(old_image.known_alias_tags)
            new_tags = set(input_image.all_tags)
            new_nodes = set(input_image.nodes)
            new_aliases = set(input_image.known_alias_tags)
            # Merge nodes, tags, aliases, prepulled, and update size
            old_image.all_tags = list(old_tags.union(new_tags))
            old_image.nodes = list(old_nodes.union(new_nodes))
            old_image.known_alias_tags = list(old_aliases.union(new_aliases))
            old_image.prepulled = old_image.prepulled & input_image.prepulled
            if old_image.size is None:
                old_image.size = input_image.size  # We're going to assume we
                # don't have inconsistent sizes; if we do, something is badly
                # wrong, but we use the size for, at most, display, so it's not
                # worth blowing up over.
        return image_map

    # Phase 2
    def get_node_cache(self) -> List[Node]:
        """Determine which images are cached on each node."""
        return self._update_node_cache(
            self.state.nodes,
            self.determine_image_prepull_status(self.state.images),
        )

    # Phase 2A
    def _update_node_cache(
        self, nodes: List[Node], image_list: List[NodeTagImage]
    ) -> List[Node]:
        """Update which images are cached on each node."""
        node_cache: List[Node] = list()
        digest_map: Dict[str, Dict[str, Any]] = dict()
        for node_tag_image in image_list:
            image = node_tag_image.to_image()
            if image.digest not in digest_map:
                digest_map[image.digest] = dict()
            digest_map[image.digest]["image"] = image
            digest_map[image.digest]["nodes"] = node_tag_image.nodes
        for node in nodes:
            for node_tag_image in image_list:
                digest = node_tag_image.digest
                nodes_for_digest = digest_map[digest]["nodes"]
                if node.name in nodes_for_digest:
                    node.cached.append(digest_map[digest]["image"])
            node_cache.append(node)
        return node_cache

    # Utility method used in multiple phases of get_prepulls()
    def determine_image_prepull_status(
        self, images: List[NodeTagImage]
    ) -> List[NodeTagImage]:
        # This works across nodes to see whether if an image is on
        # one eligible node, it is on all eligible nodes
        nodes = self.state.nodes
        r: List[NodeTagImage] = list()
        eligible_node_names = set([x.name for x in nodes if x.eligible])
        for i in images:
            image_node_names = set(i.nodes)
            prepulled: bool = True
            if eligible_node_names - image_node_names:
                # Only use eligible nodes to determine prepulled status
                prepulled = False
            c = copy(i)  # Leave the original intact
            c.prepulled = prepulled  # Update copy's prepull status
            r.append(c)
        return r

    def filter_node_images_to_desired_menu(
        self, all_images: List[NodeTagImage]
    ) -> Dict[str, NodeTagImage]:
        """Used in get_prepulls() and get_menu_images()"""
        menu_tag_count = {
            RSPTagType.RELEASE: self.config.num_releases,
            RSPTagType.WEEKLY: self.config.num_weeklies,
            RSPTagType.DAILY: self.config.num_dailies,
        }
        return self.filter_node_images_to_desired(
            tag_count=menu_tag_count, all_images=all_images
        )

    def filter_node_images_to_desired(
        self, tag_count: Dict[RSPTagType, int], all_images: List[NodeTagImage]
    ) -> Dict[str, NodeTagImage]:
        """Convenience method used by get_spawner_images (which is asking for
        one of each of daily, weekly, and release) as well as the above"""
        desired_images: Dict[str, NodeTagImage] = dict()
        # First: consolidate tags in all images.
        images: List[NodeTagImage] = list()
        for image in all_images:
            images.append(self.tag_client.consolidate_tags(image))
        for image in images:
            # First pass: find recommended tag, put it at top
            if (
                image.best_tag
                and image.best_tag == self.config.recommended_tag
            ):
                desired_images[image.best_tag] = image
        running_count: Dict[RSPTagType, int] = dict()
        for tag_type in RSPTagType:
            if tag_count.get(tag_type) is None:
                tag_count[tag_type] = 0
            running_count[tag_type] = 0
        for image in images:
            if image.best_nonalias_tag_type is None:
                self.logger.warning(f"Image type is None: {image}")
                continue
            tag_type = image.best_nonalias_tag_type
            running_count[tag_type] += 1
            if running_count[tag_type] > tag_count[tag_type]:
                continue
            if image.best_tag:
                desired_images[image.best_tag] = image
        return desired_images

    def get_spawner_images(self) -> SpawnerImages:
        """GET /nublado/spawner/v1/images"""
        images = self.get_images()

        spawner_tag_count = {
            RSPTagType.RELEASE: 1,
            RSPTagType.WEEKLY: 1,
            RSPTagType.DAILY: 1,
        }

        desired_images = self.filter_node_images_to_desired(
            spawner_tag_count, images
        )

        # We will have four images here: recommended, latest release,
        # latest weekly, and latest daily, in that order (because of the
        # ordering of the RSPTag enum).

        desired_list = [x.to_image() for x in list(desired_images.values())]

        return SpawnerImages(
            recommended=desired_list[0],
            latest_release=desired_list[1],
            latest_weekly=desired_list[2],
            latest_daily=desired_list[3],
        )

    def get_menu_images(self) -> DisplayImages:
        """Used to construct the spawner form."""
        node_images = self.get_images()

        menu_node_images = self.filter_node_images_to_desired_menu(node_images)

        available_menu_node_images = self._filter_node_images_by_availability(
            menu_node_images
        )

        raw_images = self.state.images
        images: List[NodeTagImage] = list()
        for image in raw_images:
            images.append(self.tag_client.consolidate_tags(image))

        menu_images = DisplayImages()
        for node_image in available_menu_node_images:
            available = available_menu_node_images[node_image]
            menu_images.menu[available.best_tag] = available.to_image()
        for image in images:
            menu_images.all[image.best_tag] = image.to_image()
        return menu_images

    def _filter_node_images_by_availability(
        self, menu_node_images: Dict[str, NodeTagImage]
    ) -> Dict[str, NodeTagImage]:
        r: Dict[str, NodeTagImage] = dict()
        for k in menu_node_images:
            if menu_node_images[k].prepulled:
                r[k] = menu_node_images[k]
        return r

    def get_required_prepull_images(self) -> Dict[str, List[str]]:
        """This is the method to identify everything that needs pulling.
        This will generate a dictionary where image paths are the
        keys and a list of nodes that need those images are the values.

        This can then be used by the executor to spawn pods with those images
        on the nodes that need them.
        """

        status = self.get_prepulls()
        pending = status.images.pending

        required_pulls: Dict[str, List[str]] = dict()
        eligible_node_names = [x.name for x in self.state.nodes if x.eligible]
        for img in pending:
            if img.missing is not None:
                for i in img.missing:
                    if i in eligible_node_names:
                        if img.path not in required_pulls:
                            required_pulls[img.path] = list()
                        required_pulls[img.path].append(i)
        self.logger.debug(f"Required pulls by node: {required_pulls}")
        return required_pulls
