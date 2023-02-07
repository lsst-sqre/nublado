"""Configuration dependency."""
from typing import Optional

from ..config import Configuration
from ..constants import CONFIGURATION_PATH


class ConfigurationDependency:
    def __init__(self, filename: str = CONFIGURATION_PATH) -> None:
        self._filename: str = filename
        self._config: Optional[Configuration] = None
        #  Defer initialization until first use.

    async def __call__(
        self,
    ) -> Configuration:
        return self.config

    @property
    def config(self) -> Configuration:
        if self._config is None:
            self._config = Configuration.from_file(
                self._filename,
            )
        return self._config

    def set_filename(self, path: str) -> None:
        """Change the settings path and reload."""
        self._filename = path
        self._config = Configuration.from_file(
            filename=self._filename,
        )


configuration_dependency = ConfigurationDependency()
