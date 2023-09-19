"""Configuration for the prepuller.

This is both part of the `~juputerlabcontroller.config.Config` object for the
whole lab controller and information we return via the prepuller status route,
so it has to live in its own file separate from the rest of the configuration.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from safir.pydantic import CamelCaseModel

__all__ = [
    "DockerSourceConfig",
    "GARSourceConfig",
    "PrepullerConfig",
]


class DockerSourceConfig(CamelCaseModel):
    """Docker Registry from which to get images."""

    type: Literal["docker"] = Field(..., title="Type of image source")
    registry: str = Field(
        "docker.io",
        examples=["lighthouse.ceres"],
        title="hostname (and optional port) of Docker repository",
    )
    repository: str = Field(
        ...,
        examples=["library/sketchbook"],
        title="Docker repository path to lab image (no tag or digest)",
    )


class GARSourceConfig(CamelCaseModel):
    """Google Artifact Registry from which to get images.

    The Google Artifact Repository naming convention is unfortunate. It uses
    ``repository`` for a specific management level of the Google Artifact
    Registry within a Google project and without specifying the name of the
    image, unlike the terminology that is used elsewhere where the registry is
    the hostname and the repository is everything else except the tag and hash.

    Everywhere else, repository is used in the non-Google sense. In this
    class, the main class uses the Google terminology to avoid confusion, and
    uses ``path`` for what everything else calls the repository.
    """

    type: Literal["google"] = Field(..., title="Type of image source")
    location: str = Field(
        ...,
        examples=["us-central1"],
        title="Region or multiregion of registry",
        description=(
            "This is the same as the hostname of the registry but with the"
            " ``-docker.pkg.dev`` suffix removed."
        ),
    )
    project_id: str = Field(
        ...,
        examples=["ceres-lighthouse-6ab4"],
        title="Google Cloud Platform project ID of registry",
    )
    repository: str = Field(
        ...,
        examples=["library"],
        title="Google Artifact Registry repository name",
    )
    image: str = Field(
        ...,
        examples=["sketchbook"],
        title="Google Artifact Registry image name",
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


class PrepullerConfig(CamelCaseModel):
    """Configuration for the prepuller."""

    source: DockerSourceConfig | GARSourceConfig = Field(
        ..., title="Source of images"
    )
    recommended_tag: str = Field(
        "recommended",
        examples=["recommended"],
        title="Tag of recommended image",
        description=(
            "This image will be shown first on the menu as the default choice."
        ),
    )
    num_releases: int = Field(
        1,
        examples=[1],
        title="Number of releases to prepull",
        description=(
            "This many releases, starting with the most recent, will be"
            " prepulled and shown as menu selections."
        ),
        ge=0,
    )
    num_weeklies: int = Field(
        2,
        examples=[2],
        title="Number of weeklies to prepull",
        description=(
            "This many weeklies, starting with the most recent, will be"
            " prepulled and shown as menu selections."
        ),
        ge=0,
    )
    num_dailies: int = Field(
        3,
        examples=[3],
        title="Number of dailies to prepull",
        description=(
            "This many dailies, starting with the most recent, will be"
            " prepulled and shown as menu selections."
        ),
        ge=0,
    )
    cycle: int | None = Field(
        None,
        examples=[27],
        title="Limit to this cycle number (XML schema version)",
        description=(
            "Telescope and Site images contain software implementing a"
            " specific XML schema version, and it is not safe to use"
            " software using a different XML schema version. If this is"
            " set, only images with a matching cycle will be shown in the"
            " spawner menu."
        ),
    )
    pin: list[str] | None = Field(
        None,
        examples=[["d_2077_10_23"]],
        title="List of image tags to prepull and pin to the menu",
        description=(
            "Forces images to be cached and pinned to the menu even when they"
            " would not normally be prepulled (not recommended or within the"
            " latest dailies, weeklies, or releases). This can be used to add"
            " additional images to the menu or to force resolution of the"
            " image underlying the recommended tag when Docker is used as the"
            " image source so that we can give it a proper display name."
        ),
    )
    alias_tags: list[str] = Field(
        [],
        examples=[["recommended_cycle0027"]],
        title="Additional alias tags",
        description=(
            "These tags will automatically be recognized as alias tags rather"
            " than unknown, which results in different sorting and better"
            " human-readable descriptions."
        ),
    )
