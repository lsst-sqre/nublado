"""Application configuration for the purger."""

from pathlib import Path
from typing import Annotated, Self

import yaml
from pydantic import Field, SecretStr
from safir.logging import LogLevel, Profile, configure_logging
from safir.pydantic import HumanTimedelta

from ..config.base import CamelEnvFirstSettings
from .constants import POLICY_FILE, ROOT_LOGGER

__all__ = ["Config"]


class Config(CamelEnvFirstSettings):
    """Configuration for the purger."""

    policy_file: Annotated[Path, Field(title="Policy file location")] = (
        POLICY_FILE
    )

    debug: Annotated[
        bool,
        Field(
            title="Show debug output and log style",
            description=(
                "If True, then log level will be set to debug and will"
                " non-structured, human-readable output."
            ),
        ),
    ] = False

    dry_run: Annotated[
        bool, Field(title="Report rather than execute plan")
    ] = False

    future_duration: Annotated[
        HumanTimedelta | None,
        Field(title="Duration into the future to use for planning purposes"),
    ] = None

    log_profile: Annotated[Profile, Field(title="Logging profile")] = (
        Profile.production
    )

    log_level: Annotated[LogLevel, Field(title="Log level")] = LogLevel.INFO

    add_timestamp: Annotated[
        bool, Field(title="Add timestamp to log lines")
    ] = False

    alert_hook: Annotated[
        SecretStr | None,
        Field(
            title="Slack webhook URL used for sending alerts",
            description=(
                "An https URL, which should be considered secret."
                " If not set or set to `None`, this feature will be disabled."
            ),
        ),
    ] = None

    @classmethod
    def from_file(cls, path: Path) -> Self:
        """Construct the configuration from a YAML file.

        Parameters
        ----------
        path
            Path to the configuration file in YAML.

        Returns
        -------
        nublado.purger.config.Config
            The corresponding configuration.
        """
        with path.open("r") as f:
            config = cls.model_validate(yaml.safe_load(f))
        config.configure_logging()
        return config

    def configure_logging(self) -> None:
        """Configure logging based on the purger configuration."""
        if self.debug:
            log_level = LogLevel.DEBUG
            log_profile = Profile.development
        else:
            log_level = self.log_level
            log_profile = self.log_profile

        configure_logging(
            profile=log_profile,
            log_level=log_level,
            add_timestamp=self.add_timestamp,
            name=ROOT_LOGGER,
        )
