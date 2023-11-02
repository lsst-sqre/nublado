"""Models for prepuller."""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, Field

from ..domain.rspimage import RSPImage
from .prepuller_config import PrepullerConfig


class Image(BaseModel):
    reference: str = Field(
        ...,
        title="Docker reference of image",
        examples=["lighthouse.ceres/library/sketchbook:latest_daily"],
        description="cf. https://docs.docker.com/registry/introduction/",
    )
    tag: str = Field(..., title="Image tag", examples=["w_2023_04"])
    name: str = Field(
        ...,
        examples=["Latest Daily (Daily 2077_10_23)"],
        title="Human-readable version of image tag",
    )
    digest: str | None = Field(
        None,
        examples=[
            (
                "sha256:e693782192ecef4f7846ad2b21"
                "b1574682e700747f94c5a256b5731331a2eec2"
            )
        ],
        title="Digest of image",
    )


class PrepulledImage(Image):
    """Used to display available images."""

    aliases: list[str] = Field(
        [], title="Other aliases", examples=[["recommended", "latest_weekly"]]
    )
    prepulled: bool = Field(
        False,
        examples=[True],
        title="Whether image is prepulled to all eligible nodes",
    )

    @classmethod
    def from_rsp_image(cls, image: RSPImage, nodes: set[str]) -> Self:
        """Convert from an `~jupyterhub.models.domain.RSPImage`.

        Parameters
        ----------
        image
            Source image.
        nodes
            Nodes this image must be on to count as prepulled.

        Returns
        -------
        PrepulledImage
            Converted image.
        """
        aliases = list(image.aliases)
        if image.alias_target:
            aliases.append(image.alias_target)
        return cls(
            reference=image.reference,
            tag=image.tag,
            aliases=sorted(aliases),
            name=image.display_name,
            digest=image.digest,
            prepulled=image.nodes >= nodes,
        )


class NodeImage(Image):
    size: int | None = Field(
        None, examples=[8675309], title="Size in bytes of image if known"
    )
    nodes: list[str] = Field([], title="Nodes on which image is cached")
    missing: list[str] | None = Field(
        None, title="Nodes not caching the image"
    )


class SpawnerImages(BaseModel):
    recommended: PrepulledImage | None = Field(None, title="Recommended image")
    latest_weekly: PrepulledImage | None = Field(None, title="Latest weekly")
    latest_daily: PrepulledImage | None = Field(None, title="Latest daily")
    latest_release: PrepulledImage | None = Field(None, title="Latest release")
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
        examples=["gke-science-platform-d-core-pool-78ee-03baf5c9-7w75"],
        title="Name of node",
    )
    eligible: bool = Field(
        True, examples=[True], title="Whether node is eligible for prepulling"
    )
    comment: str | None = Field(
        None,
        examples=["Cordoned because of disk problems"],
        title="Reason for node ineligibility",
    )
    cached: list[str] = Field([], title="Image references cached on this node")


class PrepullerStatus(BaseModel):
    config: PrepullerConfig = Field(..., title="Prepuller configuration")
    images: PrepullerImageStatus = Field(
        ..., title="Prepuller status by image"
    )
    nodes: list[Node] = Field(..., title="Prepuller status by node")
