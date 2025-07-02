"""Application configuration for the purger."""

from pathlib import Path
from typing import Annotated

from pydantic import Field, HttpUrl
from safir.logging import LogLevel, Profile
from safir.pydantic import CamelCaseModel, HumanTimedelta

from .constants import ENV_PREFIX, POLICY_FILE


class LoggingConfig(CamelCaseModel):
    """Configuration for the purger's logs."""

    profile: Annotated[
        Profile,
        Field(
            title="Logging profile",
            validation_alias=ENV_PREFIX + "LOGGING_PROFILE",
        ),
    ] = Profile.production

    log_level: Annotated[
        LogLevel,
        Field(title="Log level", validation_alias=ENV_PREFIX + "LOG_LEVEL"),
    ] = LogLevel.INFO

    add_timestamp: Annotated[
        bool,
        Field(
            title="Add timestamp to log lines",
            validation_alias=ENV_PREFIX + "ADD_TIMESTAMP",
        ),
    ] = False

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "profile": self.profile.value,
            "log_level": self.log_level.value,
            "add_timestamp": self.add_timestamp,
        }


class Config(CamelCaseModel):
    """Top-level configuration for the purger."""

    policy_file: Annotated[
        Path,
        Field(
            title="Policy file location",
            validation_alias=ENV_PREFIX + "POLICY_FILE",
        ),
    ] = POLICY_FILE

    dry_run: Annotated[
        bool,
        Field(
            title="Report rather than execute plan",
            validation_alias=ENV_PREFIX + "DRY_RUN",
        ),
    ] = False

    future_duration: Annotated[
        HumanTimedelta | None,
        Field(
            title="Duration into the future to use for planning purposes",
            validation_alias=ENV_PREFIX + "FUTURE_DURATION",
        ),
    ] = None

    logging: Annotated[
        LoggingConfig,
        Field(
            title="Logging configuration",
        ),
    ] = LoggingConfig()

    alert_hook: Annotated[
        HttpUrl | None,
        Field(
            title="Slack webhook URL used for sending alerts",
            description=(
                "An https URL, which should be considered secret."
                " If not set or set to `None`, this feature will be disabled."
            ),
            validation_alias=ENV_PREFIX + "ALERT_HOOK",
        ),
    ] = None

    def to_dict(self) -> dict[str, str | bool | dict[str, str | bool]]:
        obj: dict[str, str | bool | dict[str, str | bool]] = {
            "policy_file": str(self.policy_file),
            "dry_run": self.dry_run,
            "logging": self.logging.to_dict(),
        }
        if self.alert_hook:
            obj["alert_hook"] = str(self.alert_hook)
        if self.future_duration:
            secs = int(self.future_duration.total_seconds())
            obj["future_duration"] = f"{secs}s"
        return obj
