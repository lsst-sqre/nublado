"""Models for prepuller."""

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, root_validator, validator


def _gar_registry_error() -> None:
    assert False, "GAR repositories must be '<location>-docker.pkg-dev'"


class Image(BaseModel):
    path: str
    tag: str
    name: str
    digest: Optional[str]
    prepulled: Optional[bool]


class Node(BaseModel):
    name: str
    eligible: bool = True
    comment: Optional[str]
    cached: List[Image] = []


class NodeImage(Image):
    nodes: List[Node] = []
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
    def registry_defined(
        cls, values: Dict[str, Any], pre: bool = True
    ) -> Dict[str, Any]:
        gar, docker = values.get("gar"), values.get("docker")
        if (gar is not None and docker is None) or (
            gar is None and docker is not None
        ):
            assert False, "Exactly one of 'docker' or 'gar' must be defined"
        return values

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
    def untagged_path(self):
        # Return the canonical path to the image (without the tag)
        p = self.registry
        gar = self.gar
        if gar is not None:
            p += f"/{gar.projectId}/{gar.repository}/{gar.image}"
        else:
            p += f"/{self.docker.repository}"
        return p

    @property
    def tagged_path(self) -> str:
        return f"{self.untagged_path()}:{self.tag}"

    @property
    def digest_path(self) -> str:
        p = self.untagged_path()
        if self.digest is not None:
            p += "@{self.digest}"
        return p


class PrepullerContents(BaseModel):
    prepulled: List[NodeImage] = []
    pending: List[NodeImage] = []


class PrepullerStatus(BaseModel):
    config: Config
    images: PrepullerContents
    nodes: List[Node]
