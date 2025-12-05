"""Application configuration for the purger."""

from pathlib import Path
from typing import Annotated, Self

import yaml
from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)
from safir.logging import LogLevel, Profile, configure_logging
from safir.pydantic import HumanTimedelta

from .constants import (
    ENV_PREFIX,
    POLICY_FILE,
    ROOT_LOGGER,
)

__all__ = ["Config"]


class EnvFirstSettings(BaseSettings):
    """Base class for Pydantic settings with environment overrides.

    Classes that inherit from this base class will prioritize environment
    variables over arguments to the class constructor.
    """

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX, extra="forbid", validate_by_name=True
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Override the sources of settings.

        Deactivate :file:`.env` and secret file support, since Phalanx doesn't
        use them. Allow environment variables to override init parameters,
        since init parameters come from the YAML configuration file and we
        want environment variables to take precedent.

        Ideally, this code would use Pydantic's ``YamlConfigSettingsSource``,
        but unfortunately it currently doesn't support overriding the path to
        the configuration file dynamically, which is required by the test
        suite.
        """
        return (env_settings, init_settings)


class Config(EnvFirstSettings):
    """Configuration for the purger."""

    policy_file: Annotated[
        Path,
        Field(
            title="Policy file location",
            validation_alias=AliasChoices(
                ENV_PREFIX + "POLICY_FILE", "policyFile"
            ),
        ),
    ] = POLICY_FILE

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
        bool,
        Field(
            title="Report rather than execute plan",
            validation_alias=AliasChoices(ENV_PREFIX + "DRY_RUN", "dryRun"),
        ),
    ] = False

    future_duration: Annotated[
        HumanTimedelta | None,
        Field(
            title="Duration into the future to use for planning purposes",
            validation_alias=AliasChoices(
                ENV_PREFIX + "FUTURE_DURATION", "futureDuration"
            ),
        ),
    ] = None

    log_profile: Annotated[
        Profile,
        Field(
            title="Logging profile",
            validation_alias=AliasChoices(
                ENV_PREFIX + "LOG_PROFILE", "logProfile"
            ),
        ),
    ] = Profile.production

    log_level: Annotated[
        LogLevel,
        Field(
            title="Log level",
            validation_alias=AliasChoices(
                ENV_PREFIX + "LOG_LEVEL", "logLevel"
            ),
        ),
    ] = LogLevel.INFO

    add_timestamp: Annotated[
        bool,
        Field(
            title="Add timestamp to log lines",
            validation_alias=AliasChoices(
                ENV_PREFIX + "ADD_TIMESTAMP", "addTimestamp"
            ),
        ),
    ] = False

    alert_hook: Annotated[
        SecretStr | None,
        Field(
            title="Slack webhook URL used for sending alerts",
            description=(
                "An https URL, which should be considered secret."
                " If not set or set to `None`, this feature will be disabled."
            ),
            validation_alias=AliasChoices(
                ENV_PREFIX + "ALERT_HOOK", "alertHook"
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
        Config
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
