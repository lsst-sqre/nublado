"""Helper classes for prepuller.  Generally these are annotated versions
of the external objects with fields we don't want to export to the user
but which are handy for internal bookkeeping
"""
from typing import Dict, List, Optional, TypeAlias

from kubernetes_asyncio.client.models import V1ContainerImage

from ..external.prepuller import Image
from .tag import Tag, TagList

NodeContainers: TypeAlias = Dict[str, List[V1ContainerImage]]


class NodeTagImage(Image):
    nodes: List[str] = []
    known_alias_tags: List[str] = []
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


DigestToNodeTagImages: TypeAlias = Dict[str, NodeTagImage]


class ExtTag(Tag):
    config_aliases: Optional[List[str]] = None
    node: Optional[str] = None
    size: Optional[int] = None
