"""Helper classes for prepuller.  Generally these are annotated versions
of the external objects with fields we don't want to export to the user
but which are handy for internal bookkeeping
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, TypeAlias

from ....storage.k8s import ContainerImage
from ..external.prepuller import Image, NodeList
from .tag import Tag, TagList, TagType

NodeContainers: TypeAlias = Dict[str, List[ContainerImage]]


@dataclass
class NodeTagImage:
    path: str
    name: str
    digest: str
    tags: Dict[str, str]
    size: int
    prepulled: bool
    tag: str = ""
    nodes: List[str] = field(default_factory=list)
    known_alias_tags: List[str] = field(default_factory=list)
    tagobjs: TagList = TagList(all_tags=[])
    image_type: Optional[TagType] = None

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
        other_names: List[str] = []

        if recommended in self.tags:
            primary_tag = recommended
            primary_name = self.tags[recommended]
            del self.tags[recommended]

        self.tagobjs = TagList()
        self.tagobjs.all_tags = []
        for t in self.tags:
            self.tagobjs.all_tags.append(Tag.from_tag(t))
        self.tagobjs.sort_all_tags()

        for t_obj in self.tagobjs.all_tags:
            if primary_name == "":
                primary_name = t_obj.display_name
                primary_tag = t_obj.tag
            else:
                other_names.append(t_obj.display_name)
            if self.image_type is None:
                self.image_type = t_obj.image_type
        tag_description: str = primary_name
        if other_names:
            tag_description += f" ({', '.join(x for x in other_names)})"
        self.tags = {primary_tag: tag_description}
        self.tag = primary_tag
        self.name = tag_description
        # And now that we have only one tag, stuff it into the image path
        self.path = f"{self.path}:{self.tag}"
        return


DigestToNodeTagImages: TypeAlias = Dict[str, NodeTagImage]


@dataclass
class ExtTag(Tag):
    config_aliases: List[str] = field(default_factory=list)
    node: str = ""
    size: int = -1


@dataclass
class NodePool:
    nodes: NodeList

    def eligible_nodes(self) -> List[str]:
        return [x.name for x in self.nodes if x.eligible]
