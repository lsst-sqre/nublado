"""Models for jupyterlab-controller."""

from typing import Dict, List, Optional, Union

from pydantic import BaseModel


class Image(BaseModel):
    url: str
    tag: str
    name: str
    hash: Optional[str]
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


class PrepulledImageDisplayList:
    List[Union[Dict[str, Image], Dict[str[List[Image]]]]]


class DockerDefinition:
    repository: str


class GARDefinition:
    repository: str
    image: str
    projectId: str
    location: str


class ImageUrlAndName:
    url: str
    name: str


class Config:
    registry: str
    docker: Optional[DockerDefinition]
    gar: Optional[GARDefinition]
    recommended: str = "recommended"
    numReleases: int = 1
    numWeeklies: int = 2
    numDailies: int = 3
    cycle: Optional[int]
    pin: Optional[List[ImageUrlAndName]]
    aliasTags: Optional[List[str]]


class PrepullerContents:
    prepulled: List[NodeImage] = []
    pending: List[NodeImage] = []


class PrepullerStatus:
    config: Config
    images: PrepullerContents
    nodes: List[Node]
