"""Configuration for the prepuller.

This is both part of the `~juputerlabcontroller.config.Config` object for the
whole lab controller and information we return via the prepuller status route,
so it has to live in its own file separate from the rest of the configuration.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import Extra, Field, root_validator
from safir.pydantic import CamelCaseModel

__all__ = [
    "DockerSource",
    "GARSource",
    "PrepullerConfigBase",
    "PrepullerConfigDocker",
    "PrepullerConfigGAR",
]


class PrepullerConfigBase(CamelCaseModel):
    """Base configuration for the prepuller."""

    recommended_tag: str = Field(
        "recommended",
        example="recommended",
        title="Tag of recommended image",
        description=(
            "This image will be shown first on the menu as the default choice."
        ),
    )
    num_releases: int = Field(
        1,
        example=1,
        title="Number of releases to prepull",
        description=(
            "This many releases, starting with the most recent, will be"
            " prepulled and shown as menu selections."
        ),
        ge=0,
    )
    num_weeklies: int = Field(
        2,
        example=2,
        title="Number of weeklies to prepull",
        description=(
            "This many weeklies, starting with the most recent, will be"
            " prepulled and shown as menu selections."
        ),
        ge=0,
    )
    num_dailies: int = Field(
        3,
        example=3,
        title="Number of dailies to prepull",
        description=(
            "This many dailies, starting with the most recent, will be"
            " prepulled and shown as menu selections."
        ),
        ge=0,
    )
    cycle: Optional[int] = Field(
        None,
        example=27,
        title="Limit to this cycle number (XML schema version)",
        description=(
            "Telescope and Site images contain software implementing a"
            " specific XML schema version, and it is not safe to use"
            " software using a different XML schema version. If this is"
            " set, only images with a matching cycle will be shown in the"
            " spawner menu."
        ),
    )
    pin: Optional[list[str]] = Field(
        None,
        example=["d_2077_10_23"],
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
        example=["recommended_cycle0027"],
        title="Additional alias tags",
        description=(
            "These tags will automatically be recognized as alias tags rather"
            " than unknown, which results in different sorting and better"
            " human-readable descriptions."
        ),
    )


class DockerSource(CamelCaseModel):
    """Docker Registry from which to get images."""

    registry: str = Field(
        "docker.io",
        example="lighthouse.ceres",
        title="hostname (and optional port) of Docker repository",
    )
    repository: str = Field(
        ...,
        example="library/sketchbook",
        title="Docker repository path to lab image (no tag or digest)",
    )

    class Config:
        extra = Extra.forbid


class GARSource(CamelCaseModel):
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

    location: str = Field(
        ...,
        example="us-central1",
        title="Region or multiregion of registry",
        description=(
            "This is the same as the hostname of the registry but with the"
            " ``-docker.pkg.dev`` suffix removed."
        ),
    )
    project_id: str = Field(
        ...,
        example="ceres-lighthouse-6ab4",
        title="Google Cloud Platform project ID of registry",
    )
    repository: str = Field(
        ...,
        example="library",
        title="Google Artifact Registry repository name",
    )
    image: str = Field(
        ...,
        example="sketchbook",
        title="Google Artifact Registry image name",
    )

    class Config:
        extra = Extra.forbid

    @property
    def registry(self) -> str:
        """Hostname holding the registry."""
        return f"{self.location}-docker.pkg.dev"

    @property
    def parent(self) -> str:
        """Parent string for searches in Google Artifact Repository."""
        return (
            f"projects/{self.project_id}/locations/{self.location}"
            f"/repositories/{self.repository}/dockerImages/{self.image}"
        )

    @property
    def path(self) -> str:
        """What everything else calls a repository."""
        return f"{self.project_id}/{self.repository}/{self.image}"


class PrepullerConfigDocker(PrepullerConfigBase):
    """Prepuller configuration using Docker."""

    docker: DockerSource = Field(..., title="Docker Registry to use")

    @root_validator(pre=True)
    def _allow_empty_dict(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Delete empty ``gar`` dict to simplify Helm chart values files."""
        if "gar" in values and not values["gar"]:
            del values["gar"]
        return values


class PrepullerConfigGAR(PrepullerConfigBase):
    """Prepuller configuration using Google Artifact Registry."""

    gar: GARSource = Field(..., title="Google Artifact Registry to use")

    @root_validator(pre=True)
    def _allow_empty_dict(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Delete empty ``docker`` dict to simplify Helm chart values files."""
        if "docker" in values and not values["docker"]:
            del values["docker"]
        return values
