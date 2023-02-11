"""This is its own file because it's part of the domain Configuration object,
and we need to avoid circular imports."""

from typing import Any, Dict, List, Optional

from pydantic import Field, root_validator
from safir.pydantic import CamelCaseModel


class DockerDefinition(CamelCaseModel):
    registry: str = Field(
        "docker.io",
        name="registry",
        example="lighthouse.ceres",
        title="hostname (and optional port) of Docker repository",
    )
    repository: str = Field(
        ...,
        name="repository",
        example="library/sketchbook",
        title="Docker repository path to lab image (no tag or digest)",
    )


class GARDefinition(CamelCaseModel):
    repository: str = Field(
        ...,
        name="repository",
        example="library",
        title="Google Artifact Registry 'repository'",
        description="item between project and image in constructed path",
    )
    image: str = Field(
        ...,
        name="image",
        example="sketchbook",
        title="Google Artifact Registry image name",
    )
    project_id: str = Field(
        ...,
        name="project_id",
        example="ceres-lighthouse-6ab4",
        title="GCP Project ID for project containing the Artifact Registry",
    )
    registry: str = Field(
        ...,
        name="registry",
        example="us-central1-docker.pkg.dev",
        title="Hostname of Google Artifact Registry",
        description=(
            "Should be a regional or multiregional identifier prepended "
            "to '-docker.pkg.dev', e.g. 'us-docker.pkg.dev' or "
            "'us-central1-docker.pkg.dev'"
        ),
        regex=r".*-docker\.pkg\.dev$",
    )


class PrepullerConfiguration(CamelCaseModel):
    """See https://sqr-059.lsst.io for how this is used."""

    docker: Optional[DockerDefinition] = None
    gar: Optional[GARDefinition] = None
    recommended_tag: str = Field(
        "recommended",
        name="recommended",
        example="recommended",
        title="Image tag to use as `recommended` image",
    )
    num_releases: int = Field(
        1,
        name="num_releases",
        example=1,
        title="Number of Release images to prepull and display in menu",
    )
    num_weeklies: int = Field(
        2,
        name="num_weeklies",
        example=2,
        title="Number of Weekly images to prepull and display in menu",
    )
    num_dailies: int = Field(
        3,
        name="num_dailies",
        example=3,
        title="Number of Daily images to prepull and display in menu",
    )
    cycle: Optional[int] = Field(
        None,
        name="cycle",
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
        name="pin",
        example=["d_2077_10_23"],
        title="List of image tags to prepull and pin to the menu",
        description=(
            "Forces images to be cached and pinned to the menu even when they"
            " would not normally be prepulled. This is primarily used to force"
            " prepulling of the image underlying the recommended tag so that"
            " we can resolve it to a proper display name."
        ),
    )
    alias_tags: List[str] = Field(
        default_factory=list,
        name="alias_tags",
        example=["recommended_cycle0027"],
        title="Additional alias tags for this instance.",
    )

    @root_validator
    def registry_defined(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        klist = list(values.keys())
        if (
            "gar" in klist
            or "docker" in klist
            and not ("gar" in klist and "docker" in klist)
        ):
            return values
        raise RuntimeError("Exactly one of 'docker' or 'gar' must be defined")

    @property
    def registry(self) -> str:
        """The image registry (hostname and optional port)."""
        if self.gar:
            return self.gar.registry
        elif self.docker:
            return self.docker.registry
        else:
            # This is impossible due to validation, but mypy doesn't know that.
            raise RuntimeError("PrepullerConfiguration with no docker or gar")

    @property
    def repository(self) -> str:
        """The image repository (Docker reference without the host or tag)."""
        if self.gar:
            return (
                f"{self.gar.project_id}/{self.gar.repository}"
                f"/{self.gar.image}"
            )
        elif self.docker:
            return self.docker.repository
        else:
            # This is impossible due to validation, but mypy doesn't know that.
            raise RuntimeError("PrepullerConfiguration with no docker or gar")
