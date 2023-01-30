"""The arbitrator reconciles cluster node state with repository node state
so that it knows what images need prepulling.
"""


from typing import Dict, List, Optional

from structlog.stdlib import BoundLogger

from ...models.domain.prepuller import DisplayImages
from ...models.tag import RSPTag, RSPTagList, RSPTagType
from ...models.v1.prepuller import (
    Image,
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
        # Phase 1: determine desired tags.
        desired_rsptags = self.get_desired_rsptags()
        # Phase 2: determine eligible nodes
        eligible_nodes = [x.name for x in self.state.nodes if x.eligible]

        # Phase 3: update status for local images
        img_status = self.update_image_status(desired_rsptags, eligible_nodes)

        # Phase 4: construct node list with cached images
        nodelist = self.recalculate_node_cache(self.state.nodes, img_status)

        status = PrepullerStatus(
            config=self.config, images=img_status, nodes=nodelist
        )
        return status

    # Phase 1
    def get_desired_rsptags(self, bot: bool = False) -> RSPTagList:
        """This returns the desired tags for either prepulling or bot user
        use.  If the ``bot`` parameter is True, it will return one (the
        latest) daily, weekly, and release tag, as well as the recommended
        tag.  If the ``bot`` parameter is False, it will return the
        count of each tag type specified in the prepuller configuration.
        """
        remote = self.state.remote_images.by_digest
        desired: List[RSPTag] = list()
        recommended: Optional[RSPTag] = None
        release: List[RSPTag] = list()
        weekly: List[RSPTag] = list()
        daily: List[RSPTag] = list()
        r_count = self.config.num_releases
        w_count = self.config.num_weeklies
        d_count = self.config.num_dailies
        if bot:
            r_count = 1
            w_count = 1
            d_count = 1
        for digest in remote:
            if (
                (recommended is not None)
                and (len(release) >= r_count)
                and (len(weekly) >= w_count)
                and (len(daily) >= d_count)
            ):
                # We have all the tags we want
                break
            seen: Dict[str, bool] = dict()
            rsp_list = remote[digest]
            for rsptag in rsp_list:
                if rsptag.tag == self.config.recommended_tag:
                    recommended = rsptag
                    rsptag.image_type = RSPTagType.ALIAS
                    seen[digest] = True
                    continue
                if (
                    rsptag.image_type == RSPTagType.RELEASE
                    and len(release) < r_count
                    and digest not in seen
                ):
                    release.append(rsptag)
                    seen[digest] = True
                    continue
                if (
                    rsptag.image_type == RSPTagType.WEEKLY
                    and len(weekly) < w_count
                    and digest not in seen
                ):
                    weekly.append(rsptag)
                    seen[digest] = True
                    continue
                if (
                    rsptag.image_type == RSPTagType.DAILY
                    and len(daily) < d_count
                    and digest not in seen
                ):
                    daily.append(rsptag)
                    seen[digest] = True
                    continue
        if recommended:
            desired.insert(0, recommended)
        desired.extend(release)
        desired.extend(weekly)
        desired.extend(daily)
        taglist = RSPTagList(tags=desired)
        return taglist

    # Phase 3
    def update_image_status(
        self, desired: RSPTagList, eligible_nodes: List[str]
    ) -> PrepullerContents:
        desired_by_digest = desired.tag_map.by_digest
        present_by_digest = self.state.local_images
        eligible = set(eligible_nodes)
        status = PrepullerContents(prepulled=list(), pending=list())
        for digest in desired_by_digest:
            if digest in present_by_digest:
                # We have it on at least one node...possibly not an
                # eligible one
                image = present_by_digest[digest]
                present_nodes = set(image.nodes)
                if eligible <= present_nodes:
                    # It exists on all eligible nodes
                    status.prepulled.append(
                        NodeImage(
                            path=image.path,
                            name=image.name,
                            digest=digest,
                            nodes=eligible_nodes,
                        )
                    )
                    continue
                # It exists on some but not all eligible nodes
                needed = eligible - present_nodes
                present = eligible & present_nodes
                status.pending.append(
                    NodeImage(
                        path=image.path,
                        name=image.name,
                        digest=digest,
                        nodes=list(present),
                        missing=list(needed),
                    )
                )
            else:
                # It's missing on all nodes
                rsptag = desired_by_digest[digest][0]
                status.pending.append(
                    NodeImage(
                        path=rsptag.image_ref,
                        name=rsptag.tag,
                        digest=digest,
                        nodes=list(),
                        missing=eligible_nodes,
                    )
                )
        return status

    # Phase 4
    def recalculate_node_cache(
        self, nodes: List[Node], images: PrepullerContents
    ) -> List[Node]:
        node_dict: Dict[str, Node] = dict()
        # Make dict for node list
        for n in nodes:
            node_dict[n.name] = Node(
                name=n.name,
                eligible=n.eligible,
                comment=n.comment,
                cached=list(),
            )
        for prepulled in images.prepulled:
            img = Image(
                path=prepulled.path,
                digest=prepulled.digest,
                name=prepulled.name,
                tags=dict(),
            )
            for node in prepulled.nodes:
                node_dict[node].cached.append(img)
        for pending in images.pending:
            img = Image(
                path=pending.path,
                digest=pending.digest,
                name=pending.name,
                tags=dict(),
            )
            for node in pending.nodes:
                node_dict[node].cached.append(img)
        return list(node_dict.values())

    def get_spawner_images(self) -> SpawnerImages:
        """GET /nublado/spawner/v1/images"""
        # Phase 1: determine desired tags.
        image_list = self.get_desired_rsptags(bot=True).to_imagelist()
        # Phase 2: get all tags
        all = RSPTagList(
            tags=list(self.state.remote_images.by_tag.values())
        ).to_imagelist()
        return SpawnerImages(
            recommended=image_list[0],
            latest_release=image_list[1],
            latest_weekly=image_list[2],
            latest_daily=image_list[3],
            all=all,
        )

    def get_menu_images(self) -> DisplayImages:
        """Used to construct the spawner form."""

        image_menu = self.get_desired_rsptags().to_imagelist()
        all = RSPTagList(
            tags=list(self.state.remote_images.by_tag.values())
        ).to_imagelist()
        menu_images = DisplayImages()
        for image in image_menu:
            menu_images.menu[image.name] = image
        for image in all:
            first_tag = list(image.tags.keys())[0]
            menu_images.all[first_tag] = image
        return menu_images

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
        for img in pending:
            path = img.path
            if img.missing is not None:
                for i in img.missing:
                    if path not in required_pulls:
                        required_pulls[path] = list()
                    required_pulls[path].append(i)
        return required_pulls
