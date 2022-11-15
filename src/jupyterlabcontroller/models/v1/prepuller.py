"""Models for prepuller."""
from __future__ import annotations

from typing import Dict, List, Optional, TypeAlias, Union

from pydantic import BaseModel, Field

from .prepuller_config import PrepullerConfig

TagToNameMap = Dict[str, str]


class PartialImage(BaseModel):
    path: str = Field(
        ...,
        title="path",
        example="lighthouse.ceres/library/sketchbook:latest_daily",
        description=(
            "Full Docker registry path (cf."
            " https://docs.docker.com/registry/introduction/ )"
            " for lab image."
        ),
    )
    name: str = Field(
        ...,
        title="name",
        example="Latest Daily (Daily 2077_10_23)",
        description=("Human-readable version of image tag"),
    )
    digest: str = Field(
        ...,
        title="digest",
        example=(
            "sha256:e693782192ecef4f7846ad2b21"
            "b1574682e700747f94c5a256b5731331a2eec2"
        ),
        description="(presumably-unique) digest of image contents",
    )


class Image(PartialImage):
    tags: TagToNameMap = Field(
        ...,
        title="tags",
        description="Map between tag and its display name",
    )
    size: int = Field(
        -1,
        title="size",
        example=8675309,
        description="Size in bytes of image.  -1 if image size is unknown.",
    )
    prepulled: bool = Field(
        False,
        title="prepulled",
        example=False,
        description="Whether image is prepulled to all eligible nodes.",
    )

    @property
    def references(self) -> List[str]:
        r = [f"{self.path}@{self.digest}"]
        for tag in self.tags:
            r.append(f"{self.path}:{tag}")
        return r


"""GET /nublado/spawner/v1/images"""
# sqr-066 is not very clear about this--its use of "list" is strange.  Let's
# assume the resulting output is correct, in which case it will be a
# dict of DisplayImages, with one key representing the best tag for each
# image, and a final key, "all", representing a list of all available images.

DisplayImage: TypeAlias = Dict[str, Image]
DisplayImages: TypeAlias = Dict[str, Union[Image, DisplayImage]]

"""GET /nublado/spawner/v1/prepulls"""


# We will need some fancy validation rules for the compound types.

# "config" section

# This lives in PrepullerConfig


# "images" section


class Node(BaseModel):
    name: str = Field(
        ...,
        title="name",
        example="gke-science-platform-d-core-pool-78ee-03baf5c9-7w75",
        description="Name of node",
    )
    eligible: bool = Field(
        True,
        title="eligible",
        example=True,
        description="Whether node is eligible for prepulling",
    )
    comment: str = Field(
        "",
        title="comment",
        example="Cordoned because of disk problems.",
        description=(
            "Empty if node is eligible, but a human-readable"
            " reason for ineligibility if it is not."
        ),
    )
    cached: List[Image] = Field(
        list(),
        title="cached",
        description="List of images cached on this node",
    )


class NodeImage(PartialImage):
    nodes: List[Node] = Field(
        list(),
        title="nodes",
        description=(
            "List of nodes that should have a complete set of images "
            "prepulled."
        ),
    )
    missing: Optional[List[Node]] = Field(
        None,
        title="missing",
        description=(
            "List of nodes that should have a set of images prepulled"
            " but that have not yet completed."
        ),
    )


class PrepullerContents(BaseModel):
    prepulled: List[NodeImage] = Field(
        list(),
        title="prepulled",
        description=(
            "List of nodes that have all desired images completely"
            " prepulled"
        ),
    )
    pending: List[NodeImage] = Field(
        list(),
        title="pending",
        description=(
            "List of nodes that do not yet have all desired images"
            " prepulled"
        ),
    )


# "nodes" section
# It's just a List[Node]


class PrepullerStatus(BaseModel):
    config: PrepullerConfig
    images: PrepullerContents
    nodes: List[Node]
