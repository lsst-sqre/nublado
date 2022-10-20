"""Prepull images to nodes.  This requires node inspection and a DaemonSet.
"""
from copy import copy
from typing import Any, Dict, List, Optional, Set, Tuple

from fastapi import Depends
from kubernetes_asyncio.client import api_client
from kubernetes_asyncio.client.models import V1ContainerImage
from safir.dependencies.logger import logger_dependency
from structlog.stdlib import BoundLogger

from ..dependencies.k8s_corev1_api import corev1_api_dependency
from ..models.prepuller import Config, Image, Node, NodePool
from ..models.tag import Tag, TagList
from ..runtime.config import controller_config

# Internal classes that extend pre-existing glasses in ways we can use.


class V1ContainerWithConfig(V1ContainerImage):
    config: Optional[Config] = None


class NodeTagConfigImage(Image):
    nodes: List[str] = []
    known_alias_tags: List[str] = []
    config: Optional[Config]
    tagobjs: List[Tag]

    def get_tag_objs(self) -> TagList:
        return TagList(all_tags=self.tagobjs)

    def to_image(self) -> Image:
        return Image(
            path=self.path,
            tags=self.tags,
            name=self.name,
            digest=self.digest,
            size=self.size,
            prepulled=self.prepulled,
        )


NodeContainers = Dict[str, List[V1ContainerWithConfig]]

DigestToNodeTagConfigImages = Dict[str, NodeTagConfigImage]


class ExtTag(Tag):
    config_aliases: Optional[List[str]] = None
    node: Optional[str] = None
    size: Optional[int] = None


async def _get_data_from_k8s(
    logger: BoundLogger = Depends(logger_dependency),
    api: api_client = Depends(corev1_api_dependency),
) -> Tuple[Dict[str, Node], NodeContainers]:
    logger.debug("Listing nodes and their image contents.")
    resp = await api.list_node()
    all_images_by_node: NodeContainers = {}
    node_dict: Dict[str, Node] = {}
    for n in resp.items:
        nn = n.metadata.name
        eligible, comment = _node_eligible(nn)
        node_dict[nn] = Node(name=nn, eligible=eligible, comment=comment)
        all_images_by_node[nn] = []
        for ci in n.status.images:
            all_images_by_node[nn].append(copy(ci))
    logger.debug(f"All images on nodes: {all_images_by_node}")
    return (node_dict, all_images_by_node)


async def get_current_image_and_node_state(
    logger: BoundLogger = Depends(logger_dependency),
) -> Tuple[List[Image], List[Node]]:
    node_dict, all_images_by_node = await _get_data_from_k8s()
    configs = _load_prepuller_config()
    logger.debug("Constructing image state.")
    image_list = _construct_current_image_state(all_images_by_node, configs)
    logger.debug("Constructed image state.")
    eligible_nodes = NodePool(nodes=list(node_dict.values())).eligible_nodes()
    logger.debug("Calculating image prepull status")
    prepulled_images = _update_prepulled_images(eligible_nodes, image_list)
    logger.debug("Calculating node cache state")
    nodes = _update_node_cache(node_dict, prepulled_images)
    images = [x.to_image() for x in prepulled_images]
    return (images, nodes)


def _update_prepulled_images(
    eligible: List[str], image_list: List[NodeTagConfigImage]
) -> List[NodeTagConfigImage]:
    r: List[NodeTagConfigImage] = []
    se: Set[str] = set(eligible)
    prepulled = True
    for i in image_list:
        sn: Set[str] = set(i.nodes)
        if sn.difference(se):
            prepulled = False
        c = copy(i)
        c.prepulled = prepulled
        r.append(c)
    return r


def _update_node_cache(
    nodes: Dict[str, Node], image_list: List[NodeTagConfigImage]
) -> List[Node]:
    r: List[Node] = []
    tagobjs: List[Tag]
    dmap: Dict[str, Dict[str, Any]] = {}
    for i in image_list:
        img = i.to_image()
        dmap[img.digest]["img"] = img
        dmap[img.digest]["nodes"] = i.nodes
    for node in nodes:
        for i in image_list:
            dg = i.digest
            nl = dmap[dg]["nodes"]
            if node in nl:
                nodes[node].cached.append(dmap[dg]["img"])
        r.append(nodes[node])
    return r


def _node_eligible(node_name: str) -> Tuple[bool, str]:
    """Stub implementation."""
    _ = node_name
    return (True, "")


def _load_prepuller_config() -> List[Config]:
    r: List[Config] = []
    prepuller_config_obj: List[Any] = controller_config["prepuller"]["configs"]
    for c_o in prepuller_config_obj:
        r.append(Config(**c_o))
    return r


def _construct_current_image_state(
    all_images_by_node: NodeContainers,
    configs: List[Config],
    logger: BoundLogger = Depends(logger_dependency),
) -> List[NodeTagConfigImage]:
    """Return a list of all images on all nodes (subject to list length
    limitations from K8s).
    """

    # Filter images by config, tagging each image with its associated config
    # (needed for alias resolution)

    filtered_images = _filter_images_by_config(all_images_by_node, configs)

    # Convert to extended Tags.  We will still have duplicates.
    exttags: List[ExtTag] = _get_exttags_from_images(filtered_images)

    # Deduplicate and convert to NodeTagConfigImages.

    node_images: List[NodeTagConfigImage] = _get_images_from_exttags(exttags)
    logger.debug("Filtered, deduplicated images: {node_images}")
    return node_images


def _get_images_from_exttags(
    exttags: List[ExtTag],
    logger: BoundLogger = Depends(logger_dependency),
) -> List[NodeTagConfigImage]:
    dmap: DigestToNodeTagConfigImages = {}
    for exttag in exttags:
        digest = exttag.digest
        if digest is None:
            logger.error("Missing digest for {exttag.image_ref}")
            continue
        img = NodeTagConfigImage(
            path=_extract_path_from_image_ref(exttag.image_ref),
            digest=digest,
            name=exttag.display_name,
            size=exttag.size,
            nodes=[exttag.node],
            known_alias_tags=exttag.config_aliases,
            tags={exttag.tag: exttag.display_name},
        )
        if digest not in dmap:
            logger.debug(f"Adding {digest} as {img.path}:{exttag.tag}")
            dmap[digest] = img
        else:
            extant_image = dmap[digest]
            if img.path != extant_image.path:
                logger.warning(
                    f"Image {digest} found as {img.path} "
                    + f"and also {extant_image.path}."
                )
                continue
            extant_image.tags.update(img.tags)
            if (
                exttag.node is not None
                and exttag.node not in extant_image.nodes
            ):
                extant_image.nodes.append(exttag.node)
            if exttag.config_aliases is not None:
                for alias in exttag.config_aliases:
                    if alias not in extant_image.known_alias_tags:
                        extant_image.known_alias_tags.append(alias)
    return list(dmap.values())


def _get_exttags_from_images(nc: NodeContainers) -> List[ExtTag]:
    r: List[ExtTag] = []
    for node in nc:
        ctrs = nc[node]
        for ctr in ctrs:
            t = _make_exttags_from_ctr(ctr, node)
            r.extend(t)
    return r


def _make_exttags_from_ctr(
    ctr: V1ContainerWithConfig, node: str
) -> List[ExtTag]:
    r: List[ExtTag] = []
    digest: str = ""
    for c in ctr.names:
        # Extract the digest, making sure we don't have conflicting
        # digests.
        if "@sha256:" in c:
            _nd = c.split("@")[-1]
            if not digest:
                digest = _nd
            assert digest == _nd, f"{c} has multiple digests"
        for c in ctr.names:
            # Start over and do it with tags.  Skip the digest as
            # just-another-tag.  That does mean there's no way to get
            # untagged images out of the config.
            if "@sha256:" in c:
                continue
            tag = c.split(":")[-1]
            config_aliases: List[str] = []
            if ctr.config is not None and ctr.config.aliasTags is not None:
                config_aliases = ctr.config.aliasTags
            basic_tag = Tag.from_tag(
                tag=tag, image_ref=c, digest=digest, alias_tags=config_aliases
            )
            tagobj = ExtTag(*basic_tag)
            tagobj.node = node
            r.append(tagobj)
    return r


def _node_containers_to_images(nc: NodeContainers) -> List[NodeTagConfigImage]:
    r: List[NodeTagConfigImage] = []
    for node in nc:
        for ctr in nc[node]:
            img = image_from_container(ctr, node)
            r.append(img)
    return r


def image_from_container(
    ctr: V1ContainerImage, node: str
) -> NodeTagConfigImage:
    path = _extract_path_from_v1_container(ctr)
    size = ctr.sizeBytes
    digest = ""
    tagobjs: List[Tag] = []
    for c in ctr.names:
        # Extract the digest, making sure we don't have conflicting
        # digests.
        if "@sha256:" in c:
            _nd = c.split("@")[-1]
            if not digest:
                digest = _nd
            assert digest == _nd, f"Image at {path} has multiple digests"
    for c in ctr.names:
        # Start over and do it with tags.
        if "@sha256:" in c:
            continue
        tag = c.split(":")[-1]
        tagobj = Tag.from_tag(tag=tag, image_ref=c, digest=digest)
        tagobjs.append(tagobj)
    tags: Dict[str, str] = {}
    for t in tagobjs:
        tags[t.tag] = t.display_name
    r = NodeTagConfigImage(
        digest=digest,
        path=path,
        tags=tags,
        tagobj=tagobjs,
        size=size,
        prepulled=False,
        name=list(tags.values())[0],  # Arbitrary
    )
    return r


def _extract_image_name(c: Config) -> str:
    if c.gar is not None:
        return c.gar.image
    if c.docker is not None:
        return c.docker.repository.split("/")[-1]
    assert False, "Config {c} sets neither 'gar' nor 'docker'!"


def _extract_path_from_v1_container(c: V1ContainerImage) -> str:
    return _extract_path_from_image_ref(c.names[0])


def _extract_path_from_image_ref(tname: str) -> str:
    # Remove the specifier from either a digest or a tagged image
    if "@sha256:" in tname:
        # Everything before the '@'
        untagged = tname.split("@")[0]
    else:
        # Everything before the last ':'
        untagged = ":".join(tname.split(":")[:-1])
    return untagged


def _filter_images_by_config(
    images: NodeContainers, cfgs: List[Config]
) -> NodeContainers:
    r: NodeContainers = {}
    for cfg in cfgs:
        name = _extract_image_name(cfg)
        for node in images:
            for c in images[node]:
                path = _extract_path_from_v1_container(c)
                img_name = path.split("/")[-1]
                if img_name == name:
                    if node not in r:
                        r[node] = []
                    t = copy(c)
                    t.config = cfg
                    r[node].append(t)
    return r
