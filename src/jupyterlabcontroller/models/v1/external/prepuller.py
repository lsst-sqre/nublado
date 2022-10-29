"""Models for prepuller."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, root_validator, validator

TagToNameMap = Dict[str, str]


class Image(BaseModel):
    path: str
    tags: TagToNameMap
    name: str
    digest: str
    size: Optional[int]
    prepulled: Optional[bool]

    @property
    def references(self) -> List[str]:
        r: List[str] = [f"{self.path}@{self.digest}"]
        for tag in self.tags:
            r.append(f"{self.path}:{tag}")
        return r

    def use_best_name(self) -> None:
        # TODO: from the tag hash map, pick the "best" name.  What does that
        # mean?  Dunno yet, so I'm picking the first one.
        for t in self.tags:
            self.name = self.tags[t]
            break


class Node(BaseModel):
    name: str
    eligible: bool = True
    comment: str = ""
    cached: List[Image] = []


class NodeImage(Image):
    nodes: List[Node] = []


class NodeImageWithMissing(NodeImage):
    missing: List[Node] = []


# We will need some fancy validation rules for the compound types.


class PrepulledImageDisplayList(BaseModel):
    List[Union[Dict[str, Image], Dict[str, List[Image]]]]


class DockerDefinition(BaseModel):
    repository: str


class GARDefinition(BaseModel):
    repository: str
    image: str
    projectId: str
    location: Optional[str]


class ImagePathAndName(BaseModel):
    path: str
    name: str


class Config(BaseModel):
    registry: str = "registry.hub.docker.com"
    docker: Optional[DockerDefinition] = None
    gar: Optional[GARDefinition] = None
    recommended: str = "recommended"
    numReleases: int = 1
    numWeeklies: int = 2
    numDailies: int = 3
    cycle: Optional[int]
    pin: Optional[List[ImagePathAndName]]
    aliasTags: Optional[List[str]]

    @root_validator
    def registry_defined(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        for x in values.keys():
            if x == "gar" or x == "docker":
                return values
        assert False, "Exactly one of 'docker' or 'gar' must be defined"

    @validator("registry")
    def validate_registry(cls, v: str) -> str:
        # only here to ensure that registry is validated for the GAR
        # validator
        return v

    @validator("gar")
    def gar_registry_host(
        cls, v: GARDefinition, values: Dict[str, str]
    ) -> GARDefinition:
        reg = values["registry"]
        gsuf = "-docker.pkg.dev"
        if v.location is None:
            assert values["registry"].endswith(gsuf)
            v.location = reg[: (1 + len(reg) - len(gsuf))]
        else:
            assert v.location == f"{reg}-docker.pkg.dev"
        return v

    @property
    def path(self) -> str:
        # Return the canonical path to the set of tagged images
        p = self.registry
        gar = self.gar
        if gar is not None:
            p += f"/{gar.projectId}/{gar.repository}/{gar.image}"
        else:
            docker = self.docker
            if docker is not None:
                p += f"/{docker.repository}"
        return p


class PrepullerContents(BaseModel):
    prepulled: List[NodeImage] = []
    pending: List[NodeImageWithMissing] = []


class PrepullerStatus(BaseModel):
    config: Config
    images: PrepullerContents
    nodes: List[Node]


class NodePool(BaseModel):
    nodes: List[Node]

    def eligible_nodes(self) -> List[str]:
        return [x.name for x in self.nodes if x.eligible]
