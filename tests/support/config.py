"""Build test configurations for the Nublado lab controller."""

from __future__ import annotations

from pathlib import Path

from jupyterlabcontroller.config import Config
from jupyterlabcontroller.dependencies.config import configuration_dependency
from jupyterlabcontroller.dependencies.context import context_dependency

__all__ = ["configure"]


async def configure(directory: str) -> Config:
    """Configure or reconfigure with a test configuration.

    If the global process context was already initialized, stop the background
    processes and restart them with the new configuration.

    Parameters
    ----------
    directory
        Configuration directory to use.

    Returns
    -------
    Config
        New configuration.
    """
    base_path = Path(__file__).parent.parent / "configs"
    config_path = base_path / directory / "input"
    configuration_dependency.set_path(config_path / "config.yaml")
    config = configuration_dependency.config

    # Adjust the configuration to point to external objects if they're present
    # in the configuration directory.
    if (config_path / "docker_config.json").exists():
        config.docker_secrets_path = config_path / "docker_config.json"
    config.metadata_path = config_path / "metadata"

    # If the process context was initialized, meaning that we already have
    # running background processes with the old configuration, stop and
    # restart them with the new configuration.
    if context_dependency.is_initialized:
        await context_dependency.aclose()
        await context_dependency.initialize(config)

    # Return the new configuration.
    return configuration_dependency.config
