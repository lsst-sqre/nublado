"""Prepull images to nodes and answer questions about the prepull
state; requires the ability to spawn pods.  It really doesn't matter
what user we use and we don't need to mount any volumes: the only
action we take is sleeping for five seconds, so not being in NSS
doesn't make a difference, and "any non-zero uid" will work just fine.

This should be a per-process singleton, although we're not going to try to
enforce that.
"""


import asyncio
import datetime
from copy import copy
from typing import Any, Dict, List, Optional

from aiojobs import Scheduler
from structlog.stdlib import BoundLogger

from ..constants import PREPULLER_POLL_INTERVAL, PREPULLER_PULL_TIMEOUT
from ..models.domain.prepuller import (
    DigestToNodeTagImages,
    DisplayImages,
    NodeContainers,
    NodeTagImage,
    TagMap,
)
from ..models.tag import RSPTag, RSPTagList, RSPTagType, StandaloneRSPTag
from ..models.v1.prepuller import (
    Node,
    NodeImage,
    PrepullerConfiguration,
    PrepullerContents,
    PrepullerStatus,
    SpawnerImages,
)
from ..storage.docker import DockerStorageClient
from ..storage.k8s import Container, ContainerImage, K8sStorageClient, PodSpec


class PrepullerManager:
    def __init__(
        self,
        namespace: str,
        logger: BoundLogger,
        k8s_client: K8sStorageClient,
        docker_client: DockerStorageClient,
        config: PrepullerConfiguration,
    ) -> None:

        self.logger = logger
        self.namespace = namespace
        self.k8s_client = k8s_client
        self.docker_client = docker_client
        self.config = config
        self._node_state: Optional[List[Node]] = None
        self._image_state: Optional[List[NodeTagImage]] = None
        self._tag_map: Optional[TagMap] = None
        self._last_check: datetime.datetime = datetime.datetime(
            year=1970,
            month=1,
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
            tzinfo=datetime.timezone.utc,
        )
        self._schedulers: Dict[str, Scheduler] = dict()

    @property
    def needs_refresh(self) -> bool:
        if datetime.datetime.now(
            tz=datetime.timezone.utc
        ) - self._last_check > datetime.timedelta(
            seconds=PREPULLER_POLL_INTERVAL
        ):
            return True
        return False

    async def refresh_if_needed(self) -> None:
        if self.needs_refresh:
            await self.refresh_state_from_k8s()
            await self.refresh_state_from_docker_repo()
            self._last_check = datetime.datetime.now(tz=datetime.timezone.utc)

    async def get_nodes(self) -> List[Node]:
        await self.refresh_if_needed()
        if self._nodes is None:
            raise RuntimeError("Failed to retrieve node state from k8s")
        return self._nodes

    async def get_eligible_nodes(self) -> List[Node]:
        return [x for x in await self.get_nodes() if x.eligible]

    async def get_images(self) -> List[NodeTagImage]:
        await self.refresh_if_needed()
        if self._images is None:
            raise RuntimeError("Failed to retrieve image state from k8s")
        return self._images

    async def get_prepulled_images(self) -> List[NodeTagImage]:
        self.logger.debug("Calculating image prepull status")
        return self._update_prepulled_images(
            await self.get_nodes(), await self.get_images()
        )

    async def get_enabled_prepulled_images(self) -> List[NodeTagImage]:
        self.logger.debug("Calculating image prepull status")
        present_images = await self.get_images()
        remote_tags = await self._make_tags_from_tag_map()
        available_remote_images = await self.get_available_images(remote_tags)
        available_images = self._merge_local_and_remote_images(
            present_images, available_remote_images
        )

        return self._update_prepulled_images(
            await self.get_nodes(), available_images
        )

    def _make_digest_map(
        self, imgs: List[NodeTagImage]
    ) -> Dict[str, NodeTagImage]:
        imgmap: Dict[str, NodeTagImage] = dict()
        for i in imgs:
            dig = i.digest
            if dig not in imgmap:
                imgmap[dig] = i
            o = imgmap[dig]
            old_tags = set(o.all_tags)
            old_nodes = set(o.nodes)
            old_aliases = set(o.known_alias_tags)
            new_tags = set(i.all_tags)
            new_nodes = set(i.nodes)
            new_aliases = set(i.known_alias_tags)
            # Merge nodes, tags, aliases, prepulled, and update size
            o.all_tags = list(old_tags.union(new_tags))
            o.nodes = list(old_nodes.union(new_nodes))
            o.known_alias_tags = list(old_aliases.union(new_aliases))
            o.prepulled = o.prepulled & i.prepulled
            if o.size is None:
                o.size = i.size
        return imgmap

    def _merge_local_and_remote_images(
        self,
        local: List[NodeTagImage],
        remote: List[NodeTagImage],
    ) -> List[NodeTagImage]:
        validated_local = self._validate_digests(local, remote)
        all_img = copy(validated_local)
        all_img.extend(remote)
        image_map = self._make_digest_map(all_img)
        return [self.consolidate_tags(x) for x in image_map.values()]

    def _validate_digests(
        self,
        local: List[NodeTagImage],
        remote: List[NodeTagImage],
    ) -> List[NodeTagImage]:
        for l_img in local:
            if not self._validate_single_image(l_img, remote):
                l_img.nodes = list()  # It needs repulling
        return local

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

    async def get_node_cache(self) -> List[Node]:
        self.logger.debug("Calculating node cache state")
        return self._update_node_cache(
            await self.get_nodes(), await self.get_prepulled_images()
        )

    async def get_tag_map(self) -> TagMap:
        await self.refresh_if_needed()
        if self._tag_map is None:
            raise RuntimeError(
                "Failed to retrieve tag map from docker "
                f"repository {self.config.path}"
            )
        return self._tag_map

    async def _make_tags_from_tag_map(self) -> List[RSPTag]:
        tagmap = await self.get_tag_map()
        available_tagobjs: List[RSPTag] = list()
        for dig in tagmap.by_digest:
            for tag in tagmap.by_digest[dig]:
                available_tagobjs.append(
                    RSPTag.from_tag(
                        tag=tag,
                        digest=dig,
                        image_ref=self.config.path,
                    )
                )
        return available_tagobjs

    async def get_available_images(
        self, tags: List[RSPTag]
    ) -> List[NodeTagImage]:
        return [
            self.consolidate_tags(x)
            for x in self._get_deduplicated_images_from_tags(tags)
        ]

    async def get_prepulls(self) -> PrepullerStatus:
        node_images = await self.get_enabled_prepulled_images()
        nodes = await self.get_node_cache()

        eligible_nodes = [x for x in nodes if x.eligible]

        menu_node_images = await self.filter_node_images_to_desired_menu(
            node_images
        )

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
                        nodes=await self._nodes_present(img, eligible_nodes),
                    )
                )
            else:
                pending.append(
                    NodeImage(
                        path=img.path,
                        name=img.name,
                        digest=img.digest,
                        nodes=await self._nodes_present(img, eligible_nodes),
                        missing=await self._nodes_missing(img, eligible_nodes),
                    )
                )
        images = PrepullerContents(prepulled=prepulled, pending=pending)
        status = PrepullerStatus(
            config=self.config, images=images, nodes=nodes
        )
        self.logger.debug(f"Prepuller status: {status}")
        return status

    async def _nodes_present(
        self, img: NodeTagImage, nodes: List[Node]
    ) -> List[Node]:
        return [x for x in nodes if x.name in img.nodes]

    async def _nodes_missing(
        self, img: NodeTagImage, nodes: List[Node]
    ) -> List[Node]:
        return [x for x in nodes if x.name not in img.nodes]

    async def get_spawner_images(self) -> SpawnerImages:
        recommended = self.config.recommended_tag
        images = await self.get_images()
        r = SpawnerImages()
        for img in images:
            tags = list(img.tags.keys())
            for t in tags:
                if t == recommended and r.recommended is None:
                    r.recommended = img.to_image()
                if t == "latest_weekly" and r.latest_weekly is None:
                    r.latest_weekly = img.to_image()
                if t == "latest_daily" and r.latest_daily is None:
                    r.latest_daily = img.to_image()
                if t == "latest_release" and r.latest_release is None:
                    r.latest_release = img.to_image()
                if (
                    r.recommended
                    and r.latest_weekly
                    and r.latest_daily
                    and r.latest_release
                ):
                    break
        return r

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

    async def get_menu_images(self) -> DisplayImages:
        node_images = await self.get_enabled_prepulled_images()

        menu_node_images = await self.filter_node_images_to_desired_menu(
            node_images
        )

        available_menu_node_images = (
            await self._filter_node_images_by_availability(menu_node_images)
        )

        raw_images = await self.get_images()
        images: List[NodeTagImage] = list()
        for image in raw_images:
            images.append(self.consolidate_tags(image))

        menu_images = DisplayImages()
        for img in available_menu_node_images:
            a_obj = available_menu_node_images[img]
            menu_images.menu[a_obj.best_tag] = a_obj.to_image()
        for image in images:
            menu_images.all[image.best_tag] = image.to_image()
        return menu_images

    async def filter_node_images_to_desired_menu(
        self, all_images: List[NodeTagImage]
    ) -> Dict[str, NodeTagImage]:
        menu_images: Dict[str, NodeTagImage] = dict()
        # First: consolidate tags in all images.
        images: List[NodeTagImage] = list()
        for img in all_images:
            images.append(self.consolidate_tags(img))
        for img in images:
            # First pass: find recommended tag, put it at top
            self.logger.debug(f"Found recommended tag: {img}")
            if img.best_tag and img.best_tag == self.config.recommended_tag:
                menu_images[img.best_tag] = img
        running_count: Dict[RSPTagType, int] = dict()
        tag_count = {
            RSPTagType.RELEASE: self.config.num_releases,
            RSPTagType.WEEKLY: self.config.num_weeklies,
            RSPTagType.DAILY: self.config.num_dailies,
        }
        for tag_type in RSPTagType:
            if tag_count.get(tag_type) is None:
                tag_count[tag_type] = 0
            running_count[tag_type] = 0
        for img in images:
            if img.best_nonalias_tag_type is None:
                self.logger.warning(f"Image type is None: {img}")
                continue
            tag_type = img.best_nonalias_tag_type
            running_count[tag_type] += 1
            if running_count[tag_type] > tag_count[tag_type]:
                continue
            if img.best_tag:
                menu_images[img.best_tag] = img
        return menu_images

    async def _filter_node_images_by_availability(
        self, menu_node_images: Dict[str, NodeTagImage]
    ) -> Dict[str, NodeTagImage]:
        r: Dict[str, NodeTagImage] = dict()
        for k in menu_node_images:
            if menu_node_images[k].prepulled:
                r[k] = menu_node_images[k]
        return r

    async def refresh_state_from_k8s(self) -> None:
        # Clear state
        self._nodes = None
        self._images = None
        # Now repopulate it
        self.logger.debug("Listing nodes and their image contents.")
        all_images_by_node = await self.k8s_client.get_image_data()
        self.logger.debug(f"All images on nodes: {all_images_by_node}")
        self.logger.debug("Constructing node pool")
        self._nodes = self._make_nodes_from_image_data(all_images_by_node)
        self.logger.debug(f"Node pool: {self._nodes}")
        self._images = self._construct_current_image_state(all_images_by_node)
        self.logger.debug(f"Images by node: {self._images}")

    async def refresh_state_from_docker_repo(self) -> None:
        # Clear state
        self._tag_map = None
        self.logger.debug(
            "Listing image tags from Docker repository " f"{self.config.path}"
        )
        self._tag_map = await self.docker_client.get_tag_map()
        self.logger.debug(f"tag_map: {self._tag_map}")

    def _make_nodes_from_image_data(
        self,
        imgdata: NodeContainers,
    ) -> List[Node]:
        return [Node(name=n) for n in imgdata.keys()]

    def _update_prepulled_images(
        self, nodes: List[Node], image_list: List[NodeTagImage]
    ) -> List[NodeTagImage]:
        r: List[NodeTagImage] = list()
        eligible = [x for x in nodes if x.eligible]
        nnames = [x.name for x in eligible]
        se = set(nnames)
        for i in image_list:
            sn = set(i.nodes)
            prepulled: bool = True
            if se - sn:
                # Only use eligible nodes to determine prepulled status
                prepulled = False
            c = copy(i)
            c.prepulled = prepulled
            r.append(c)
        return r

    def _update_node_cache(
        self, nodes: List[Node], image_list: List[NodeTagImage]
    ) -> List[Node]:
        r: List[Node] = list()
        dmap: Dict[str, Dict[str, Any]] = dict()
        for i in image_list:
            img = i.to_image()
            if img.digest not in dmap:
                dmap[img.digest] = dict()
            dmap[img.digest]["img"] = img
            dmap[img.digest]["nodes"] = i.nodes
        for node in nodes:
            for i in image_list:
                dg = i.digest
                nl = dmap[dg]["nodes"]
                if node.name in nl:
                    node.cached.append(dmap[dg]["img"])
            r.append(node)
        return r

    def _filter_images_to_enabled_nodes(
        self,
        images: List[NodeTagImage],
        nodes: List[Node],
    ) -> List[NodeTagImage]:
        eligible_nodes = [x.name for x in nodes if x.eligible]
        filtered_images: List[NodeTagImage] = list()
        for img in images:
            filtered = NodeTagImage(
                path=img.path,
                name=img.name,
                digest=img.digest,
                tags=copy(img.tags),
                size=img.size,
                prepulled=img.prepulled,
                nodes=[x for x in img.nodes if x in eligible_nodes],
                known_alias_tags=copy(img.known_alias_tags),
                tagobjs=copy(img.tagobjs),
                best_tag_type=img.best_tag_type,
            )
            filtered_images.append(filtered)
        return filtered_images

    def _construct_current_image_state(
        self,
        all_images_by_node: NodeContainers,
    ) -> List[NodeTagImage]:
        """Return annotated images representing the state of valid images
        across nodes (including those not enabled).
        """

        # Filter images by config

        filtered_images = self._filter_images_by_config(all_images_by_node)

        self.logger.debug(f"Filtered images: {filtered_images}")

        # Convert to (full) Tags.  We will still have duplicates.
        tags = self._get_tags_from_images(filtered_images)

        # Filter by cycle

        cycletags = self._filter_tags_by_cycle(tags)

        # Deduplicate and convert to NodeTagImages.

        node_images = self._get_deduplicated_images_from_tags(cycletags)
        self.logger.debug(f"Filtered, deduplicated images: {node_images}")
        return node_images

    def _get_deduplicated_images_from_tags(
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
                path=self._extract_path_from_image_ref(tag.image_ref),
                digest=digest,
                name=tag.display_name,
                size=tag.size,
                nodes=copy(tag.nodes),
                known_alias_tags=copy(tag.alias_tags),
                tags={tag.tag: tag.display_name},
                prepulled=False,
            )

            if digest not in dmap:
                self.logger.debug(f"Adding {digest} as {img.path}:{tag.tag}")
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
            self.logger.debug(f"Img before tag consolidation: {dmap[digest]}")
            self.consolidate_tags(dmap[digest])
            self.logger.debug(f"Img after tag consolidation: {dmap[digest]}")
            self.logger.debug(f"Images hash: {dmap}")
        return list(dmap.values())

    def _get_tags_from_images(self, nc: NodeContainers) -> List[RSPTag]:
        r: List[RSPTag] = list()
        for node in nc:
            ctrs = nc[node]
            for ctr in ctrs:
                t = self._make_tags_from_ctr(ctr, node)
                r.extend(t)
        return r

    def _make_tags_from_ctr(
        self,
        ctr: ContainerImage,
        node: str,
    ) -> List[RSPTag]:
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

    def _node_containers_to_images(
        self, nc: NodeContainers
    ) -> List[NodeTagImage]:
        r: List[NodeTagImage] = list()
        for node in nc:
            for ctr in nc[node]:
                img = self.image_from_container(ctr, node)
                r.append(img)
        return r

    def image_from_container(
        self, ctr: ContainerImage, node: str
    ) -> NodeTagImage:
        path = self._extract_path_from_container(ctr)
        size = ctr.size_bytes
        digest = ""
        tagobjs: List[RSPTag] = list()
        for c in ctr.names:
            # Extract the digest, making sure we don't have conflicting
            # digests.
            if "@sha256:" in c:
                _nd = c.split("@")[-1]
                if not digest:
                    digest = _nd
                if digest != _nd:
                    raise RuntimeError(f"Image at {path} has multiple digests")
        self.logger.debug(f"Found digest: {digest}")
        for c in ctr.names:
            # Start over and do it with tags.
            if "@sha256:" in c:
                continue
            tag = c.split(":")[-1]
            tagobj = RSPTag.from_tag(tag=tag, image_ref=c, digest=digest)
            tagobjs.append(tagobj)
            tags: Dict[str, str] = dict()
        tagobjlist = RSPTagList(all_tags=tagobjs)
        for t in tagobjs:
            tags[t.tag] = t.display_name
            r = NodeTagImage(
                digest=digest,
                path=path,
                tags=tags,
                tagobjs=tagobjlist,
                size=size,
                prepulled=False,
                name="",  # About to be set from instance method
                known_alias_tags=list(),
                nodes=list(),
            )
        return r

    def _extract_image_name(self) -> str:
        c = self.config
        if c.gar is not None:
            return c.gar.image
        if c.docker is not None:
            return c.docker.repository.split("/")[-1]
        raise RuntimeError(
            f"Configuration {c} sets neither 'gar' nor 'docker'!"
        )

    def _extract_path_from_container(self, c: ContainerImage) -> str:
        return self._extract_path_from_image_ref(c.names[0])

    def _extract_path_from_image_ref(self, tname: str) -> str:
        # Remove the specifier from either a digest or a tagged image
        if "@sha256:" in tname:
            # Everything before the '@'
            untagged = tname.split("@")[0]
        else:
            # Everything before the last ':'
            untagged = ":".join(tname.split(":")[:-1])
        return untagged

    def _filter_images_by_config(
        self,
        images: NodeContainers,
    ) -> NodeContainers:
        r: NodeContainers = dict()

        name = self._extract_image_name()
        self.logger.debug(f"Desired image name: {name}")
        for node in images:
            for c in images[node]:
                path = self._extract_path_from_container(c)
                img_name = path.split("/")[-1]
                if img_name == name:
                    self.logger.debug(f"Adding matching image: {img_name}")
                    if node not in r:
                        r[node] = list()
                    t = copy(c)
                    r[node].append(t)
        return r

    def _filter_tags_by_cycle(self, tags: List[RSPTag]) -> List[RSPTag]:
        if self.config.cycle is None:
            return tags
        return [t for t in tags if t.cycle == self.config.cycle]

    #
    # The rest of the file is the bits about running the prepull executor
    #

    async def run(self) -> None:
        """
        Loop until we're told to stop.
        """

        if "main" not in self._schedulers or not self._schedulers["main"]:
            self._schedulers["main"] = Scheduler(close_timeout=0.1)

        self.logger.info("Starting prepull executor.")
        self.main_job = await self._schedulers["main"].spawn(
            self.primary_loop()
        )

    async def primary_loop(self) -> None:
        try:
            while True:
                await self.prepull_images()
                await self.idle()
        except asyncio.CancelledError:
            self.logger.info("Prepull executor interrupted.")
        except Exception as e:
            self.logger.error(f"{e}")
            raise
        self.logger.info("Shutting down prepull executor.")
        await self.aclose()

    async def idle(self) -> None:
        await asyncio.sleep(PREPULLER_POLL_INTERVAL)

    async def stop(self) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close any prepull schedulers."""
        if self._schedulers:
            for image in self._schedulers:
                if image == "main":
                    continue
                self.logger.warning(f"Terminating scheduler for {image}")
                await self._schedulers["main"].spawn(
                    self._schedulers[image].close()
                )
            for image in list(self._schedulers.keys()):
                del self._schedulers[image]
        if "main" in self._schedulers and self._schedulers["main"] is not None:
            self.logger.warning(
                "Terminating main prepuller executor scheduler"
            )
            await self._schedulers["main"].close()
            del self._schedulers["main"]

    async def create_prepuller_pod_spec(
        self,
        image: str,
        node: str,
    ) -> PodSpec:
        shortname = image.split("/")[-1]

        #        user = UserInfo(
        #            username="prepuller",
        #            name="Prepuller User",
        #            uid=1000,
        #            gid=1000,
        #            groups=[
        #                UserGroup(
        #                    name="prepuller",
        #                    id=1000,
        #                )
        #            ],
        #        )
        return PodSpec(
            containers=[
                Container(
                    name=f"prepull-{shortname}",
                    command=["/bin/sleep", "5"],
                    image=image,
                    working_dir="/tmp",
                )
            ],
            node_name=node,
        )

    async def prepull_images(self) -> None:
        """This is the method to identify everything that needs pulling, and
        spawns pods with those images on the nodes that need them.
        """

        status = await self.get_prepulls()

        pending = status.images.pending

        required_pulls: Dict[str, List[str]] = dict()
        for img in pending:
            if img.missing is not None:
                for i in img.missing:
                    if i.eligible:
                        if img.path not in required_pulls:
                            required_pulls[img.path] = list()
                        required_pulls[img.path].append(i.name)
        self.logger.debug(f"Required pulls by node: {required_pulls}")
        timeout = PREPULLER_PULL_TIMEOUT
        # Parallelize across nodes but not across images
        for image in required_pulls:
            if image in self._schedulers:
                self.logger.warning(
                    f"Scheduler for image {image} already exists.  Presuming "
                    "earlier pull still in progress."
                )
                continue
            scheduler = Scheduler(close_timeout=timeout)
            self._schedulers[image] = scheduler
            tag = image.split(":")[1]
            for node in required_pulls[image]:
                await scheduler.spawn(
                    self.k8s_client.create_pod(
                        name=f"prepull-{tag}",
                        namespace=self.namespace,
                        pod=await self.create_prepuller_pod_spec(
                            image=image,
                            node=node,
                        ),
                    )
                )
            self.logger.debug(
                f"Waiting up to {timeout}s for prepuller pods {tag}."
            )
            await scheduler.close()
            del self._schedulers[image]
