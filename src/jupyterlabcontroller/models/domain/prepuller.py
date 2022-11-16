"""Helper classes for prepuller.  Generally these are annotated versions
of the external objects with fields we don't want to export to the user
but which are handy for internal bookkeeping
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, TypeAlias

from ...storage.k8s import ContainerImage
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
    best_image_type: Optional[RSPTagType] = None

    def to_image(self) -> Image:
        return Image(
            path=self.path,
            tags=self.tags,
            name=self.name,
            digest=self.digest,
            size=self.size,
            prepulled=self.prepulled,
        )

    def consolidate_tags(self, recommended: str) -> None:
        # We have a bunch of tags, potentially, for a given image.
        # Consolidate this down into a single tag to pull it by, and
        # a single (but possibly compound, like "Recommended (Weekly 2022_44)",
        # display name.

        primary_tag: str = ""
        primary_name: str = ""
        other_names: List[str] = list()

        if recommended in self.tags:
            primary_tag = recommended
            primary_name = self.tags[recommended]
            self.all_tags.append(recommended)
            del self.tags[recommended]

        self.tagobjs = RSPTagList()
        self.tagobjs.all_tags = list()
        for t in self.tags:
            self.tagobjs.all_tags.append(
                RSPTag.from_tag(t, digest=self.digest)
            )
        self.tagobjs.sort_all_tags()

        for t_obj in self.tagobjs.all_tags:
            if primary_name == "":
                primary_name = t_obj.display_name
                primary_tag = t_obj.tag
            else:
                other_names.append(t_obj.display_name)
            if self.best_image_type is None:
                self.best_image_type = t_obj.image_type
        tag_description: str = primary_name
        if other_names:
            tag_description += f" ({', '.join(x for x in other_names)})"
        self.tag = primary_tag
        self.best_tag = primary_tag
        self.name = tag_description
        # And now that we have a best tag, stuff it into the image path
        self.path = f"{self.path}:{self.tag}"
        return


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
