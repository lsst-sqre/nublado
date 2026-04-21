"""Models for specifying the sources of images."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

__all__ = ["DockerSource", "GARSource", "ImageSource"]


class DockerSource(BaseModel):
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

    def to_logging_context(self) -> dict[str, str]:
        """Build key/value pairs suitable for passing to structlog.

        Returns
        -------
        dict of str
            Key/value pairs suitable for adding to a structlog context when
            logging messages about talking to this registry.
        """
        return {"registry": self.registry, "repository": self.repository}

    def url_for(self, route: str) -> str:
        """Construct a URL to the Docker v2 API for the given route.

        Parameters
        ----------
        route
            Route fragment to add to the URL after the repository name. This
            fragment should omit any leading ``/``.

        Returns
        -------
        str
            Constructed API URL.
        """
        return f"https://{self.registry}/v2/{self.repository}/{route}"


class GARSource(BaseModel):
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
                " -docker.pkg.dev suffix removed"
            ),
            examples=["us-central1"],
        ),
    ]

    project_id: Annotated[
        str,
        Field(
            title="GCP project ID",
            description="Google Cloud Platform project ID of the registry",
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
            description="Image name",
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
        """What other Docker registries call a repository."""
        return f"{self.project_id}/{self.repository}/{self.image}"

    def to_logging_context(self) -> dict[str, str]:
        """Build key/value pairs suitable for passing to structlog.

        Returns
        -------
        dict of str
            Key/value pairs suitable for adding to a structlog context when
            logging messages about talking to this registry.
        """
        return {
            "location": self.location,
            "project_id": self.project_id,
            "repository": self.repository,
            "image": self.image,
        }


type ImageSource = Annotated[
    DockerSource | GARSource, Field(discriminator="type")
]
"""Type representing any possible image source."""
