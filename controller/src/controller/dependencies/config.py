"""Config dependency."""

from pathlib import Path

from ..config import Config
from ..constants import CONFIGURATION_PATH


class ConfigDependency:
    def __init__(self, path: Path = CONFIGURATION_PATH) -> None:
        self._path = path
        self._config: Config | None = None

    async def __call__(self) -> Config:
        return self.config

    @property
    def config(self) -> Config:
        """Load configuration if needed and return it.

        Returns
        -------
        Config
            Controller configuration.
        """
        if self._config is None:
            self._config = Config.from_file(self._path)
        return self._config

    def set_path(self, path: Path) -> None:
        """Change the configuration path and reload."""
        self._path = path
        self._config = Config.from_file(path)


configuration_dependency = ConfigDependency()
