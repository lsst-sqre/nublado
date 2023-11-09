"""Models for prepuller."""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, Field

from ..domain.rspimage import RSPImage
from .prepuller_config import PrepullerConfig


class Image(BaseModel):
    """A single Docker image that is available or prepulled."""

    reference: str = Field(
        ...,
        title="Docker reference of image",
        description=(
            "Reference of image, which includes the registry host name,"
            " the normally-two-part image name within that registry,"
            " and the tag or hash of the specific version of that image."
        ),
        examples=["lighthouse.ceres/library/sketchbook:latest_daily"],
    )

    tag: str = Field(
        ...,
        title="Image tag",
        description="Tag portion of the image reference",
        examples=["w_2023_04"],
    )

    name: str = Field(
        ...,
        title="Human-readable tag",
        description="Tag of the image formatted for humans",
        examples=["Latest Daily (Daily 2077_10_23)"],
    )

    digest: str | None = Field(
        None,
        title="Digest of image",
        description="Full digest of image if known",
        examples=[
            (
                "sha256:e693782192ecef4f7846ad2b21"
                "b1574682e700747f94c5a256b5731331a2eec2"
            )
        ],
    )


class PrepulledImage(Image):
    """Used to display available images."""

    aliases: list[str] = Field(
        [],
        title="Other aliases",
        description="Other tags that reference the same image",
        examples=[["recommended", "latest_weekly"]],
    )

    prepulled: bool = Field(
        False,
        title="Whether image is prepulled",
        description=(
            "Whether the image has been prepulled to all eligible nodes"
        ),
        examples=[True],
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
    """An available image present on at least some Kubernetes nodes."""

    size: int | None = Field(
        None,
        title="Size in bytes",
        description="Size of the image in bytes if reported by the node",
        examples=[8675309],
    )

    nodes: list[str] = Field(
        [],
        title="Nodes caching image",
        description="Nodes on which this image is cached",
        examples=[["node-1", "node-2"]],
    )

    missing: list[str] | None = Field(
        None,
        title="Nodes not caching image",
        description="Nodes on which the image should be cached but isn't",
        examples=[["node-3"]],
    )

    @classmethod
    def from_rsp_image(cls, image: RSPImage) -> Self:
        """Convert from an `~jupyterhub.models.domain.RSPImage`.

        Parameters
        ----------
        image
            Source image.

        Returns
        -------
        NodeImage
            Converted image.
        """
        return cls(
            reference=image.reference,
            tag=image.tag,
            name=image.display_name,
            digest=image.digest,
            size=image.size,
            nodes=sorted(image.nodes),
        )


class PrepullerImageStatus(BaseModel):
    """Status of the images being prepulled."""

    prepulled: list[NodeImage] = Field([], title="Successfully cached images")
    pending: list[NodeImage] = Field(
        [],
        title="Images not yet cached",
        description="Images that are missing on at least one eligible node",
    )


class Node(BaseModel):
    """Information about available images on a single Kubernetes node."""

    name: str = Field(
        ...,
        title="Name of node",
        description="Hostname of the Kubernetes node",
        examples=["gke-science-platform-d-core-pool-78ee-03baf5c9-7w75"],
    )

    eligible: bool = Field(
        True,
        title="Eligible for prepulling",
        description="Whether images should be prepulled to this node",
        examples=[True],
    )

    comment: str | None = Field(
        None,
        title="Reason for node ineligibility",
        description=(
            "If this node is not eligible for prepulling, this field contains"
            " the reason why"
        ),
        examples=["Cordoned because of disk problems"],
    )

    cached: list[str] = Field(
        [],
        title="Cached images",
        description="References of images cached on this node",
        examples=[["lighthouse.ceres/library/sketchbook:latest_daily"]],
    )


class SpawnerImages(BaseModel):
    """Images known to the Nublado controller and available for spawning.

    This model is returned by the ``/spawner/v1/images`` route.
    """

    recommended: PrepulledImage | None = Field(None, title="Recommended image")
    latest_weekly: PrepulledImage | None = Field(None, title="Latest weekly")
    latest_daily: PrepulledImage | None = Field(None, title="Latest daily")
    latest_release: PrepulledImage | None = Field(None, title="Latest release")
    all: list[PrepulledImage] = Field(..., title="All available images")


class PrepullerStatus(BaseModel):
    """Status of the image prepuller.

    This model is returned by the ``/spawner/v1/prepulls`` route.
    """

    config: PrepullerConfig = Field(..., title="Prepuller configuration")
    images: PrepullerImageStatus = Field(
        ..., title="Prepuller status by image"
    )
    nodes: list[Node] = Field(..., title="Prepuller status by node")
