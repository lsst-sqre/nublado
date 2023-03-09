"""BaseModels for prepuller."""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from ..support.util import dashify
from .prepuller_config import PrepullerConfiguration

TagToNameMap = Dict[str, str]


class PartialImage(BaseModel):
    path: str = Field(
        ...,
        name="path",
        example="lighthouse.ceres/library/sketchbook:latest_daily",
        title="Full Docker registry path for lab image",
        description="cf. https://docs.docker.com/registry/introduction/",
    )
    name: str = Field(
        ...,
        name="name",
        example="Latest Daily (Daily 2077_10_23)",
        title="Human-readable version of image tag",
    )
    digest: str = Field(
        ...,
        name="digest",
        example=(
            "sha256:e693782192ecef4f7846ad2b21"
            "b1574682e700747f94c5a256b5731331a2eec2"
        ),
        title="unique digest of image contents",
    )


class Image(PartialImage):
    tags: TagToNameMap = Field(
        ...,
        name="tags",
        title="Map between tag and its display name",
    )
    size: Optional[int] = Field(
        None,
        name="size",
        example=8675309,
        title="Size in bytes of image.  None if image size is unknown",
    )
    prepulled: bool = Field(
        False,
        name="prepulled",
        example=False,
        title="Whether image is prepulled to all eligible nodes",
    )

    @property
    def references(self) -> List[str]:
        r = [f"{self.path}@{self.digest}"]
        for tag in self.tags:
            r.append(f"{self.path}:{tag}")
        return r


"""GET /nublado/spawner/v1/images"""


class SpawnerImages(BaseModel):
    recommended: Optional[Image] = None
    latest_weekly: Optional[Image] = None
    latest_daily: Optional[Image] = None
    latest_release: Optional[Image] = None
    all: List[Image] = Field(default_factory=list)

    class Config:
        alias_generator = dashify
        allow_population_by_field_name = True


"""GET /nublado/spawner/v1/prepulls"""


# "config" section

# This comes from PrepullerConfiguration


# "images" section


class Node(BaseModel):
    name: str = Field(
        ...,
        name="name",
        example="gke-science-platform-d-core-pool-78ee-03baf5c9-7w75",
        title="Name of node",
    )
    eligible: bool = Field(
        True,
        name="eligible",
        example=True,
        title="Whether node is eligible for prepulling",
    )
    comment: str = Field(
        "",
        name="comment",
        example="Cordoned because of disk problems.",
        title="Human-readable reason for node ineligibility, else empty.",
    )
    cached: List[Image] = Field(
        default_factory=list,
        name="cached",
        title="List of images cached on this node",
    )


class NodeImage(PartialImage):
    nodes: List[str] = Field(
        default_factory=list,
        name="nodes",
        title="List of node names that should get prepulled images",
    )
    missing: Optional[List[str]] = Field(
        None,
        name="missing",
        title="List of node names whose image prepulls have not yet finished",
    )


class PrepullerContents(BaseModel):
    prepulled: List[NodeImage] = Field(
        default_factory=list,
        name="prepulled",
        title="List of nodes whose image prepulls are complete",
    )
    pending: List[NodeImage] = Field(
        default_factory=list,
        name="pending",
        title="List of nodes whose image prepulls have not yet finished",
    )


# "nodes" section
# It's just a List[Node]


class PrepullerStatus(BaseModel):
    config: PrepullerConfiguration
    images: PrepullerContents
    nodes: List[Node]
