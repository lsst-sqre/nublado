"""Prepull images to nodes.  This requires node inspection and a DaemonSet.
"""
from copy import copy
from typing import Any, Dict, List, Set, Tuple

from fastapi import Depends
from kubernetes_asyncio.client import CoreV1Api
from kubernetes_asyncio.client.models import V1ContainerImage
from safir.dependencies.logger import logger_dependency
from structlog.stdlib import BoundLogger

from ..dependencies.config import configuration_dependency
from ..dependencies.k8s import k8s_corev1api_dependency
from ..models.v1.domain.config import Config
from ..models.v1.domain.prepuller import (
    DigestToNodeTagImages,
    ExtTag,
    NodeContainers,
    NodeTagImage,
)
from ..models.v1.domain.tag import Tag
from ..models.v1.external.prepuller import Image, Node


async def get_image_data_from_k8s(
    logger: BoundLogger = Depends(logger_dependency),
    api: CoreV1Api = Depends(k8s_corev1api_dependency),
) -> NodeContainers:
    logger.debug("Listing nodes and their image contents.")
    resp = await api.list_node()
    all_images_by_node: NodeContainers = {}
    for n in resp.items:
        nn = n.metadata.name
        all_images_by_node[nn] = []
        for ci in n.status.images:
            all_images_by_node[nn].append(copy(ci))
    logger.debug(f"All images on nodes: {all_images_by_node}")
    return all_images_by_node


async def get_current_image_and_node_state(
    logger: BoundLogger = Depends(logger_dependency),
) -> Tuple[List[Image], List[Node]]:
    all_images_by_node = await get_image_data_from_k8s()
    logger.debug("Constructing initial node pool")
    initial_nodes = _make_nodes_from_image_data(all_images_by_node)
    logger.debug("Constructing image state.")
    image_list = _construct_current_image_state(all_images_by_node)
    logger.debug("Calculating image prepull status")
    prepulled_images = _update_prepulled_images(initial_nodes, image_list)
    logger.debug("Calculating node cache state")
    nodes = _update_node_cache(initial_nodes, prepulled_images)
    images = [x.to_image() for x in prepulled_images]
    return (images, nodes)


def _make_nodes_from_image_data(
    imgdata: NodeContainers,
    config: Config = Depends(configuration_dependency),
) -> List[Node]:
    cfg = config.prepuller.config
    r: List[Node] = [Node(name=n) for n in imgdata.keys()]
    _ = cfg  # TODO determine eligibility/comment based on config
    return r


def _update_prepulled_images(
    eligible: List[Node], image_list: List[NodeTagImage]
) -> List[NodeTagImage]:
    r: List[NodeTagImage] = []
    nnames = [x.name for x in eligible]
    se: Set[str] = set(nnames)
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
    nodes: List[Node], image_list: List[NodeTagImage]
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
            if node.name in nl:
                node.cached.append(dmap[dg]["img"])
        r.append(node)
    return r


def _construct_current_image_state(
    all_images_by_node: NodeContainers,
    logger: BoundLogger = Depends(logger_dependency),
) -> List[NodeTagImage]:
    """Return annotated images representing the state of valid images
    across nodes.
    """

    # Filter images by config

    filtered_images = _filter_images_by_config(all_images_by_node)

    # Convert to extended Tags.  We will still have duplicates.
    exttags: List[ExtTag] = _get_exttags_from_images(filtered_images)

    # Deduplicate and convert to NodeTagImages.

    node_images: List[NodeTagImage] = _get_images_from_exttags(exttags)
    logger.debug("Filtered, deduplicated images: {node_images}")
    return node_images


def _get_images_from_exttags(
    exttags: List[ExtTag],
    logger: BoundLogger = Depends(logger_dependency),
) -> List[NodeTagImage]:
    dmap: DigestToNodeTagImages = {}
    for exttag in exttags:
        digest = exttag.digest
        if digest is None:
            logger.error("Missing digest for {exttag.image_ref}")
            continue
        img = NodeTagImage(
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


def _make_exttags_from_ctr(ctr: V1ContainerImage, node: str) -> List[ExtTag]:
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
            # Start over and do it with tags.  Skip the digest.
            # That does mean there's no way to get untagged images out of
            # the config unless it's a pin.
            if "@sha256:" in c:
                continue
            tag = c.split(":")[-1]
            config_aliases: List[str] = []
            if ctr.config is not None and ctr.config.aliasTags is not None:
                config_aliases = ctr.config.aliasTags
            basic_tag = Tag.from_tag(
                tag=tag, image_ref=c, digest=digest, alias_tags=config_aliases
            )
            tagobj = ExtTag.parse_obj(basic_tag)
            tagobj.node = node
            r.append(tagobj)
    return r


def _node_containers_to_images(nc: NodeContainers) -> List[NodeTagImage]:
    r: List[NodeTagImage] = []
    for node in nc:
        for ctr in nc[node]:
            img = image_from_container(ctr, node)
            r.append(img)
    return r


def image_from_container(ctr: V1ContainerImage, node: str) -> NodeTagImage:
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
    r = NodeTagImage(
        digest=digest,
        path=path,
        tags=tags,
        tagobj=tagobjs,
        size=size,
        prepulled=False,
        name="",  # About to be set from instance method
    )
    r.use_best_name()
    return r


def _extract_image_name(
    config: Config = Depends(configuration_dependency),
) -> str:
    c = config.prepuller.config
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
    images: NodeContainers,
) -> NodeContainers:
    r: NodeContainers = {}

    name = _extract_image_name()
    for node in images:
        for c in images[node]:
            path = _extract_path_from_v1_container(c)
            img_name = path.split("/")[-1]
            if img_name == name:
                if node not in r:
                    r[node] = []
                t = copy(c)
                r[node].append(t)
    return r
