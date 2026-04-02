"""Pydantic settings class that prioritizes environment variables."""

from typing import override

from pydantic import AliasChoices, AliasGenerator
from pydantic.alias_generators import to_camel
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from ..constants import ENV_PREFIX

__all__ = ["CamelEnvFirstSettings"]


def _to_camel_or_env(name: str) -> AliasChoices:
    """Generate aliases for both environment variables and camel-case."""
    return AliasChoices(ENV_PREFIX + "_" + name.upper(), to_camel(name))


class CamelEnvFirstSettings(BaseSettings):
    """Base class for Pydantic settings with environment overrides.

    Classes that inherit from this base class will use add validation aliases
    in camel-case and prioritize environment variables (in all caps with
    underscores) over arguments to the class constructor. Environment
    variables must be prefixed with `~nublado.constants.ENV_PREFIX`.
    """

    model_config = SettingsConfigDict(
        alias_generator=AliasGenerator(validation_alias=_to_camel_or_env),
        extra="forbid",
        validate_by_name=True,
    )

    @override
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
