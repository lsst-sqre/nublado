"""Configuration for the prepuller.

This is both part of the `~juputerlabcontroller.config.Config` object for the
whole lab controller and information we return via the prepuller status route,
so it is defined in a separate model that can be included by both.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from ...constants import DOCKER_CREDENTIALS_PATH

__all__ = [
    "DockerSourceConfig",
    "GARSourceConfig",
    "PrepullerConfig",
]


class DockerSourceConfig(BaseModel):
    """Docker Registry from which to get images."""

    type: Literal["docker"] = Field(..., title="Type of image source")

    registry: str = Field(
        "docker.io",
        title="Docker registry",
        description=(
            "Hostname and optional port of the Docker registry holding lab"
            " images"
        ),
        examples=["lighthouse.ceres"],
    )

    repository: str = Field(
        ...,
        title="Docker repository (image name)",
        description=(
            "Docker repository path to the lab image, without tags or digests."
            " This is sometimes called the image name."
        ),
        examples=["library/sketchbook"],
    )

    credentials_path: Path = Field(
        DOCKER_CREDENTIALS_PATH,
        title="Path to Docker API credentials",
        description=(
            "Path to a file containing a JSON-encoded dictionary of Docker"
            " credentials for various registries, in the same format as"
            " the Docker configuration file and the value of a Kubernetes"
            " pull secret"
        ),
        exclude=True,
    )

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )


class GARSourceConfig(BaseModel):
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

    type: Literal["google"] = Field(..., title="Type of image source")

    location: str = Field(
        ...,
        title="Region or multiregion of registry",
        description=(
            "This is the same as the hostname of the registry but with the"
            " ``-docker.pkg.dev`` suffix removed."
        ),
        examples=["us-central1"],
    )

    project_id: str = Field(
        ...,
        title="GCP project ID",
        description="Google Cloud Platform project ID containing the registry",
        examples=["ceres-lighthouse-6ab4"],
    )

    repository: str = Field(
        ...,
        title="GAR repository",
        description="Google Artifact Registry repository name",
        examples=["library"],
    )

    image: str = Field(
        ...,
        title="GAR image name",
        description="Google Artifact Registry image name",
        examples=["sketchbook"],
    )

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )

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


class PrepullerConfig(BaseModel):
    """Configuration for the prepuller.

    This model is used as both the model for the ``images`` key in the Nublado
    controller configuration and as a component of the model returned by the
    ``/spawner/v1/prepulls`` route.
    """

    source: DockerSourceConfig | GARSourceConfig = Field(
        ..., title="Source of images"
    )

    recommended_tag: str = Field(
        "recommended",
        title="Tag of recommended image",
        description=(
            "This image will be shown first on the menu as the default choice."
        ),
        examples=["recommended"],
    )

    num_releases: int = Field(
        1,
        title="Number of releases to prepull",
        description=(
            "This many releases, starting with the most recent, will be"
            " prepulled and shown as menu selections."
        ),
        examples=[1],
        ge=0,
    )

    num_weeklies: int = Field(
        2,
        title="Number of weeklies to prepull",
        description=(
            "This many weeklies, starting with the most recent, will be"
            " prepulled and shown as menu selections."
        ),
        examples=[2],
        ge=0,
    )

    num_dailies: int = Field(
        3,
        title="Number of dailies to prepull",
        description=(
            "This many dailies, starting with the most recent, will be"
            " prepulled and shown as menu selections."
        ),
        examples=[3],
        ge=0,
    )

    cycle: int | None = Field(
        None,
        title="Limit to this cycle number (XML schema version)",
        description=(
            "Telescope and Site images contain software implementing a"
            " specific XML schema version, and it is not safe to use"
            " software using a different XML schema version. If this is"
            " set, only images with a matching cycle will be shown in the"
            " spawner menu."
        ),
        examples=[27],
    )

    pin: list[str] | None = Field(
        None,
        title="List of image tags to prepull and pin to the menu",
        description=(
            "Forces images to be cached and pinned to the menu even when they"
            " would not normally be prepulled (not recommended or within the"
            " latest dailies, weeklies, or releases). This can be used to add"
            " additional images to the menu or to force resolution of the"
            " image underlying the recommended tag when Docker is used as the"
            " image source so that we can give it a proper display name."
        ),
        examples=[["d_2077_10_23"]],
    )

    alias_tags: list[str] = Field(
        [],
        title="Additional alias tags",
        description=(
            "These tags will automatically be recognized as alias tags rather"
            " than unknown, which results in different sorting and better"
            " human-readable descriptions."
        ),
        examples=[["recommended_cycle0027"]],
    )

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )
