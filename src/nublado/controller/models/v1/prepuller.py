"""Models for prepuller."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field
from safir.pydantic import HumanTimedelta

from ...constants import DOCKER_CREDENTIALS_PATH
from ..domain.rspimage import RSPImage

__all__ = [
    "DockerSourceOptions",
    "GARSourceOptions",
    "Image",
    "Node",
    "NodeImage",
    "PrepulledImage",
    "PrepullerImageStatus",
    "PrepullerOptions",
    "PrepullerStatus",
    "SpawnerImages",
]


class DockerSourceOptions(BaseModel):
    """Docker Registry from which to get images."""

    type: Annotated[Literal["docker"], Field(title="Type of image source")]

    registry: Annotated[
        str,
        Field(
            title="Docker registry",
            description=(
                "Hostname and optional port of the Docker registry holding lab"
                " images"
            ),
            examples=["lighthouse.ceres"],
        ),
    ] = "docker.io"

    repository: Annotated[
        str,
        Field(
            title="Docker repository (image name)",
            description=(
                "Docker repository path to the lab image, without tags or"
                " digests. This is sometimes called the image name."
            ),
            examples=["library/sketchbook"],
        ),
    ]

    credentials_path: Annotated[
        Path,
        Field(
            title="Path to Docker API credentials",
            description=(
                "Path to a file containing a JSON-encoded dictionary of Docker"
                " credentials for various registries, in the same format as"
                " the Docker configuration file and the value of a Kubernetes"
                " pull secret"
            ),
            exclude=True,
        ),
    ] = DOCKER_CREDENTIALS_PATH


class GARSourceOptions(BaseModel):
    """Google Artifact Registry from which to get images.

    The Google Artifact Repository naming convention is unfortunate. It uses
    ``repository`` for a specific management level of the Google Artifact
    Registry within a Google project that does not include the name of the
    image, unlike the terminology that is used elsewhere where the registry is
    the hostname and the repository is everything else except the tag and
    hash.

    Everywhere else, repository is used in the non-Google sense. In this
    class, the main class uses the Google terminology to avoid confusion, and
    uses ``path`` for what everything else calls the repository.
    """

    type: Annotated[Literal["google"], Field(title="Type of image source")]

    location: Annotated[
        str,
        Field(
            title="Region or multiregion of registry",
            description=(
                "This is the same as the hostname of the registry but with the"
                " ``-docker.pkg.dev`` suffix removed."
            ),
            examples=["us-central1"],
        ),
    ]

    project_id: Annotated[
        str,
        Field(
            title="GCP project ID",
            description=(
                "Google Cloud Platform project ID containing the registry"
            ),
            examples=["ceres-lighthouse-6ab4"],
        ),
    ]

    repository: Annotated[
        str,
        Field(
            title="GAR repository",
            description="Google Artifact Registry repository name",
            examples=["library"],
        ),
    ]

    image: Annotated[
        str,
        Field(
            title="GAR image name",
            description="Google Artifact Registry image name",
            examples=["sketchbook"],
        ),
    ]

    @property
    def registry(self) -> str:
        """Hostname holding the registry."""
        return f"{self.location}-docker.pkg.dev"

    @property
    def parent(self) -> str:
        """Parent string for searches in Google Artifact Repository."""
        return (
            f"projects/{self.project_id}/locations/{self.location}"
            f"/repositories/{self.repository}"
        )

    @property
    def path(self) -> str:
        """What everything else calls a repository."""
        return f"{self.project_id}/{self.repository}/{self.image}"


class PrepullerOptions(BaseModel):
    """Options for the prepuller.

    The information here comes from the YAML configuration for the Nublado
    controller and is a component of the model returned by the
    ``/spawner/v1/prepulls`` route. The model for the YAML configuration also
    enables camel-case aliases, but those are not enabled here since we want
    the API to return snake-case.
    """

    source: Annotated[
        DockerSourceOptions | GARSourceOptions, Field(title="Source of images")
    ]

    refresh_interval: Annotated[
        HumanTimedelta,
        Field(
            title="Image refresh interval",
            description=(
                "How frequently to refresh the list of remote and cached"
                " images"
            ),
        ),
    ] = timedelta(minutes=5)

    recommended_tag: Annotated[
        str,
        Field(
            title="Tag of recommended image",
            description=(
                "This image will be shown first on the menu as the default"
                " choice."
            ),
            examples=["recommended"],
        ),
    ] = "recommended"

    num_releases: Annotated[
        int,
        Field(
            title="Number of releases to prepull",
            description=(
                "This many releases, starting with the most recent, will be"
                " prepulled and shown as menu selections."
            ),
            examples=[1],
            ge=0,
        ),
    ] = 1

    num_weeklies: Annotated[
        int,
        Field(
            title="Number of weeklies to prepull",
            description=(
                "This many weeklies, starting with the most recent, will be"
                " prepulled and shown as menu selections."
            ),
            examples=[2],
            ge=0,
        ),
    ] = 2

    num_dailies: Annotated[
        int,
        Field(
            title="Number of dailies to prepull",
            description=(
                "This many dailies, starting with the most recent, will be"
                " prepulled and shown as menu selections."
            ),
            examples=[3],
            ge=0,
        ),
    ] = 3

    cycle: Annotated[
        int | None,
        Field(
            title="Limit to this cycle number (XML schema version)",
            description=(
                "Telescope and Site images contain software implementing a"
                " specific XML schema version, and it is not safe to use"
                " software using a different XML schema version. If this is"
                " set, only images with a matching cycle will be shown in the"
                " spawner menu."
            ),
            examples=[27],
        ),
    ] = None

    pin: Annotated[
        list[str],
        Field(
            title="List of image tags to prepull and pin to the menu",
            description=(
                "Forces images to be cached and pinned to the menu even when"
                " they would not normally be prepulled (not recommended or"
                " within the latest dailies, weeklies, or releases). This can"
                " be used to add additional images to the menu or to force"
                " resolution of the image underlying the recommended tag when"
                " Docker is used as the image source so that we can give it a"
                " proper display name."
            ),
            examples=[["d_2077_10_23"]],
        ),
    ] = []

    alias_tags: Annotated[
        list[str],
        Field(
            title="Additional alias tags",
            description=(
                "These tags will automatically be recognized as alias tags"
                " rather than unknown tags, which results in different sorting"
                " and better human-readable descriptions."
            ),
            examples=[["recommended_cycle0027"]],
        ),
    ] = []


class Image(BaseModel):
    """A single Docker image that is available or prepulled."""

    reference: Annotated[
        str,
        Field(
            title="Docker reference of image",
            description=(
                "Reference of image, which includes the registry host name,"
                " the normally-two-part image name within that registry,"
                " and the tag or hash of the specific version of that image."
            ),
            examples=["lighthouse.ceres/library/sketchbook:latest_daily"],
        ),
    ]

    tag: Annotated[
        str,
        Field(
            title="Image tag",
            description="Tag portion of the image reference",
            examples=["w_2023_04"],
        ),
    ]

    name: Annotated[
        str,
        Field(
            title="Human-readable tag",
            description="Tag of the image formatted for humans",
            examples=["Latest Daily (Daily 2077_10_23)"],
        ),
    ]

    digest: Annotated[
        str | None,
        Field(
            title="Digest of image",
            description="Full digest of image if known",
            examples=[
                (
                    "sha256:e693782192ecef4f7846ad2b21"
                    "b1574682e700747f94c5a256b5731331a2eec2"
                )
            ],
        ),
    ] = None


class PrepulledImage(Image):
    """Used to display available images."""

    aliases: Annotated[
        list[str],
        Field(
            title="Other aliases",
            description="Other tags that reference the same image",
            examples=[["recommended", "latest_weekly"]],
        ),
    ] = []

    prepulled: Annotated[
        bool,
        Field(
            title="Whether image is prepulled",
            description=(
                "Whether the image has been prepulled to all eligible nodes"
            ),
            examples=[True],
        ),
    ] = False

    @classmethod
    def from_rsp_image(cls, image: RSPImage, nodes: set[str]) -> Self:
        """Convert from `~nublado.controller.models.domain.rspimage.RSPImage`.

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

    size: Annotated[
        int | None,
        Field(
            title="Size in bytes",
            description="Size of the image in bytes if reported by the node",
            examples=[8675309],
        ),
    ] = None

    nodes: Annotated[
        list[str],
        Field(
            title="Nodes caching image",
            description="Nodes on which this image is cached",
            examples=[["node-1", "node-2"]],
        ),
    ] = []

    missing: Annotated[
        list[str],
        Field(
            title="Nodes not caching image",
            description="Nodes on which the image should be cached but isn't",
            examples=[["node-3"]],
        ),
    ] = []

    @classmethod
    def from_rsp_image(cls, image: RSPImage) -> Self:
        """Convert from `~nublado.controller.models.domain.rspimage.RSPImage`.

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

    prepulled: Annotated[
        list[NodeImage],
        Field(title="Successfully cached images"),
    ] = []

    pending: Annotated[
        list[NodeImage],
        Field(
            title="Images not yet cached",
            description=(
                "Images that are missing on at least one eligible node"
            ),
        ),
    ] = []


class Node(BaseModel):
    """Information about available images on a single Kubernetes node."""

    name: Annotated[
        str,
        Field(
            title="Name of node",
            description="Hostname of the Kubernetes node",
            examples=["gke-science-platform-d-core-pool-78ee-03baf5c9-7w75"],
        ),
    ]

    eligible: Annotated[
        bool,
        Field(
            title="Eligible for prepulling",
            description="Whether images should be prepulled to this node",
            examples=[True],
        ),
    ] = True

    comment: Annotated[
        str | None,
        Field(
            title="Reason for node ineligibility",
            description=(
                "If this node is not eligible for prepulling, this field"
                " contains the reason why"
            ),
            examples=["Cordoned because of disk problems"],
        ),
    ] = None

    cached: Annotated[
        list[str],
        Field(
            title="Cached images",
            description="References of images cached on this node",
            examples=[["lighthouse.ceres/library/sketchbook:latest_daily"]],
        ),
    ] = []


class SpawnerImages(BaseModel):
    """Images known to the Nublado controller and available for spawning.

    This model is returned by the ``/spawner/v1/images`` route.
    """

    recommended: Annotated[
        PrepulledImage | None, Field(title="Recommended image")
    ] = None

    latest_weekly: Annotated[
        PrepulledImage | None, Field(title="Latest weekly")
    ] = None

    latest_daily: Annotated[
        PrepulledImage | None, Field(title="Latest daily")
    ] = None

    latest_release: Annotated[
        PrepulledImage | None, Field(title="Latest release")
    ] = None

    all: Annotated[list[PrepulledImage], Field(title="All available images")]


class PrepullerStatus(BaseModel):
    """Status of the image prepuller.

    This model is returned by the ``/spawner/v1/prepulls`` route.
    """

    config: Annotated[PrepullerOptions, Field(title="Prepuller configuration")]

    images: Annotated[
        PrepullerImageStatus, Field(title="Prepuller status by image")
    ]

    nodes: Annotated[list[Node], Field(title="Prepuller status by node")]
