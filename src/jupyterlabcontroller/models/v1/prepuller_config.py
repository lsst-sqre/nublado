"""This is its own file because it's part of the domain Config object, and
we need to avoid circular imports."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, root_validator, validator


class DockerDefinition(BaseModel):
    repository: str = Field(
        ...,
        title="repository",
        example="lighthouse.ceres/library/sketchbook",
        description=(
            "Docker registry path (excluding the tag or digest)"
            " to the Lab image."
        ),
    )


class GARDefinition(BaseModel):
    repository: str = Field(
        ...,
        title="repository",
        example="library",
        description=(
            "Google Artifact Registry 'repository' (between project"
            " and image in constructed path)"
        ),
    )
    image: str = Field(
        ...,
        title="image",
        example="sketchbook",
        description="Google Artifact Registry image name",
    )
    project_id: str = Field(
        ...,
        title="project_id",
        example="ceres-lighthouse-6ab4",
        description=(
            "GCP Project ID for project containing the Artifact Registry"
        ),
    )
    location: str = Field(
        ...,
        title="location",
        example="us-central1-docker.pkg.dev",
        description=(
            "Hostname of Google Artifact Registry.  Should be"
            " a regional or multiregional identifier prepended"
            " to '-docker.pkg.dev', e.g. 'us-docker.pkg.dev' or"
            " 'us-central1-docker.pkg.dev'."
        ),
    )


class ImagePathAndName(BaseModel):
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


class PrepullerConfig(BaseModel):
    """See https://sqr-059.lsst.io for how this is used."""

    registry: str = Field(
        "registry.hub.docker.com",
        title="registry",
        example="lighthouse.ceres",
        description="Hostname of Docker repository",
    )
    docker: Optional[DockerDefinition] = None
    gar: Optional[GARDefinition] = None
    recommendedTag: str = Field(
        "recommended",
        title="recommended",
        example="recommended",
        description="Image tag to use as `recommended` image",
    )
    num_releases: int = Field(
        1,
        title="num_releases",
        example=1,
        description="Number of Release images to prepull and display in menu.",
    )
    num_weeklies: int = Field(
        2,
        title="num_weeklies",
        example=2,
        description="Number of Weekly images to prepull and display in menu.",
    )
    num_dailies: int = Field(
        3,
        title="num_dailies",
        example=3,
        description="Number of Daily images to prepull and display in menu.",
    )
    cycle: Optional[int] = Field(
        None,
        title="cycle",
        example=27,
        description=(
            "Cycle number describing XML schema version of this"
            " image.  Currently only used by T&S RSP."
        ),
    )
    pin: Optional[List[ImagePathAndName]] = Field(
        None,
        title="pin",
        example=["lighthouse.ceres/library/sketchbook:d_2077_10_23"],
        description=(
            "List of images to prepull and pin to the menu, "
            "even if they would not normally be prepulled."
        ),
    )
    alias_tags: List[str] = Field(
        [],
        title="alias_tags",
        example=["recommended_cycle0027"],
        description="Additional alias tags for this instance.",
    )

    @root_validator
    def registry_defined(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        for x in values.keys():
            if x == "gar" or x == "docker":
                return values
        assert False, "Exactly one of 'docker' or 'gar' must be defined"

    @validator("registry")
    def validate_registry(cls, v: str) -> str:
        # only here to ensure that registry is validated for the GAR
        # validator
        return v

    @validator("gar")
    def gar_registry_host(
        cls, v: GARDefinition, values: Dict[str, str]
    ) -> GARDefinition:
        reg = values["registry"]
        gsuf = "-docker.pkg.dev"
        if v.location != "":
            assert v.location == f"{reg}-{gsuf}"
        else:
            v.location = f"{reg}-{gsuf}"
        return v

    @property
    def path(self) -> str:
        # Return the canonical path to the set of tagged images
        p = self.registry
        gar = self.gar
        if gar is not None:
            p += f"/{gar.projectId}/{gar.repository}/{gar.image}"
        else:
            docker = self.docker
            if docker is not None:
                p += f"/{docker.repository}"
        return p
