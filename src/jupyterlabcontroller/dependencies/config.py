"""Configuration dependency."""

from pathlib import Path
from typing import Optional

from ..config import Configuration
from ..constants import CONFIGURATION_PATH


class ConfigurationDependency:
    def __init__(self, path: Path = CONFIGURATION_PATH) -> None:
        self._path = path
        self._config: Optional[Configuration] = None

    async def __call__(self) -> Configuration:
        return self.config

    @property
    def config(self) -> Configuration:
        """Load configuration if needed and return it.

        Returns
        -------
        jupyterlabcontroller.config.Configuration
            Controller configuration.
        """
        if self._config is None:
            self._config = Configuration.from_file(self._path)
        return self._config

    def set_path(self, path: Path) -> None:
        """Change the configuration path and reload."""
        self._path = path
        self._config = Configuration.from_file(path)


configuration_dependency = ConfigurationDependency()
