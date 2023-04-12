"""Build test configurations for the Nublado lab controller."""

from __future__ import annotations

from pathlib import Path

from jupyterlabcontroller.config import Config
from jupyterlabcontroller.dependencies.config import configuration_dependency

__all__ = ["configure"]


def configure(directory: str) -> Config:
    """Generate test configuration.

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
    if (config_path / "docker_config.json").exists():
        config.docker_secrets_path = config_path / "docker_config.json"
    config.metadata_path = config_path / "metadata"
    return configuration_dependency.config
