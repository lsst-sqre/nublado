"""Models for prepuller."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from .prepuller_config import PrepullerConfiguration


class Image(BaseModel):
    reference: str = Field(
        ...,
        title="Docker reference of image",
        example="lighthouse.ceres/library/sketchbook:latest_daily",
        description="cf. https://docs.docker.com/registry/introduction/",
    )
    tag: str = Field(..., title="Image tag", example="w_2023_04")
    name: str = Field(
        ...,
        example="Latest Daily (Daily 2077_10_23)",
        title="Human-readable version of image tag",
    )
    digest: Optional[str] = Field(
        None,
        example=(
            "sha256:e693782192ecef4f7846ad2b21"
            "b1574682e700747f94c5a256b5731331a2eec2"
        ),
        title="Digest of image",
    )


class PrepulledImage(Image):
    """Used to display available images."""

    aliases: list[str] = Field(
        [], title="Other aliases", example=["recommended", "latest_weekly"]
    )
    prepulled: bool = Field(
        False,
        name="prepulled",
        example=True,
        title="Whether image is prepulled to all eligible nodes",
    )


class NodeImage(Image):
    size: Optional[int] = Field(
        None, example=8675309, title="Size in bytes of image if known"
    )
    nodes: list[str] = Field([], title="Nodes on which image is cached")
    missing: Optional[list[str]] = Field(
        None, title="Nodes not caching the image"
    )


class SpawnerImages(BaseModel):
    recommended: PrepulledImage = Field(..., title="Recommended image")
    latest_weekly: Optional[PrepulledImage] = Field(
        None, title="Latest weekly"
    )
    latest_daily: Optional[PrepulledImage] = Field(None, title="Latest daily")
    latest_release: Optional[PrepulledImage] = Field(
        None, title="Latest release"
    )
    all: list[PrepulledImage] = Field(..., title="All available images")


class PrepullerImageStatus(BaseModel):
    prepulled: list[NodeImage] = Field([], title="Successfully cached images")
    pending: list[NodeImage] = Field(
        [],
        title="Images not yet cached on all eligible nodes",
    )


class Node(BaseModel):
    name: str = Field(
        ...,
        example="gke-science-platform-d-core-pool-78ee-03baf5c9-7w75",
        title="Name of node",
    )
    eligible: bool = Field(
        True, example=True, title="Whether node is eligible for prepulling"
    )
    comment: Optional[str] = Field(
        None,
        example="Cordoned because of disk problems",
        title="Reason for node ineligibility",
    )
    cached: list[str] = Field(
        [], name="cached", title="Image references cached on this node"
    )


class PrepullerStatus(BaseModel):
    config: PrepullerConfiguration = Field(
        ..., title="Prepuller configuration"
    )
    images: PrepullerImageStatus = Field(
        ..., title="Prepuller status by image"
    )
    nodes: list[Node] = Field(..., title="Prepuller status by node")
