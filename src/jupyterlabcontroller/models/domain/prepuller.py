"""Helper classes for prepuller.  Generally these are annotated versions
of the external objects with fields we don't want to export to the user
but which are handy for internal bookkeeping
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, TypeAlias

from ..k8s import ContainerImage
from ..tag import RSPTag, RSPTagList, RSPTagType
from ..v1.prepuller import Image, Node

NodeContainers: TypeAlias = Dict[str, List[ContainerImage]]


@dataclass
class NodeTagImage:
    path: str
    name: str
    digest: str
    tags: Dict[str, str]
    size: Optional[int]
    prepulled: bool
    best_tag: str = ""
    all_tags: List[str] = field(default_factory=list)
    nodes: List[str] = field(default_factory=list)
    known_alias_tags: List[str] = field(default_factory=list)
    tagobjs: RSPTagList = RSPTagList(all_tags=list())
    best_tag_type: Optional[RSPTagType] = None
    best_nonalias_tag_type: Optional[RSPTagType] = None

    def to_image(self) -> Image:
        return Image(
            path=self.path,
            tags=self.tags,
            name=self.name,
            digest=self.digest,
            size=self.size,
            prepulled=self.prepulled,
        )


@dataclass
class DisplayImages:
    menu: Dict[str, Image] = field(default_factory=dict)
    all: Dict[str, Image] = field(default_factory=dict)


DigestToNodeTagImages: TypeAlias = Dict[str, NodeTagImage]


@dataclass
class NodeTag(RSPTag):
    node: str = ""


@dataclass
class NodePool:
    nodes: List[Node]

    @property
    def eligible(self) -> List[str]:
        return [x.name for x in self.nodes if x.eligible]


@dataclass
class TagMap:
    by_digest: Dict[str, List[str]] = field(default_factory=dict)
    by_tag: Dict[str, str] = field(default_factory=dict)
