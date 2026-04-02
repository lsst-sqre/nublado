"""Configuration for the image management command-line tool."""

from pathlib import Path
from typing import Annotated, Self

import yaml
from pydantic import ConfigDict, Field
from pydantic.alias_generators import to_camel
from safir.logging import LogLevel, Profile, configure_logging

from ..constants import ROOT_LOGGER
from ..models.images import DockerSource, GARSource
from .base import CamelEnvFirstSettings

__all__ = [
    "DockerSourceConfig",
    "GARSourceConfig",
    "ImageSourceConfig",
    "ImagesConfig",
]


class DockerSourceConfig(DockerSource):
    """Configuration for a Docker source.

    This is identical to the underlying API model except that camel-case
    aliases are enabled and unknown attributes sre forbidden, making it
    suitable for use in parsing configuration files.
    """

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )


class GARSourceConfig(GARSource):
    """Configuration for a Google Artifact Registry source.

    This is identical to the underlying API model except that camel-case
    aliases are enabled and unknown attributes sre forbidden, making it
    suitable for use in parsing configuration files.
    """

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )


type ImageSourceConfig = Annotated[
    DockerSourceConfig | GARSourceConfig, Field(discriminator="type")
]


class ImagesConfig(CamelEnvFirstSettings):
    """Configuration for Nublado image management."""

    log_level: Annotated[LogLevel, Field(title="Log level")] = LogLevel.INFO

    log_profile: Annotated[Profile, Field(title="Logging profile")] = (
        Profile.production
    )

    source: Annotated[
        ImageSourceConfig,
        Field(title="Source", description="Source of images to manage"),
    ]

    @classmethod
    def from_file(cls, path: Path, *, debug: bool | None = None) -> Self:
        """Load the images configuration from a YAML file.

        Parameters
        ----------
        path
            Path to the configuration file.
        """
        with path.open("r") as f:
            config = cls.model_validate(yaml.safe_load(f))
        if debug:
            config.log_level = LogLevel.DEBUG
        return config

    def configure_logging(self) -> None:
        """Configure logging based on the configuration."""
        configure_logging(
            name=ROOT_LOGGER,
            profile=self.log_profile,
            log_level=self.log_level,
        )
