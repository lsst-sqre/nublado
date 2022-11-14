"""Configuration dependency."""
from typing import Optional

from ..config import Config
from ..models.v1.consts import CONFIGURATION_PATH


class ConfigurationDependency:
    def __init__(self, filename: str = CONFIGURATION_PATH) -> None:
        self._filename: str = filename
        self._config: Optional[Config] = None
        #  Defer initialization until first use.

    async def __call__(
        self,
    ) -> Config:
        return self.config

    @property
    def config(self) -> Config:
        if self._config is None:
            self._config = Config.from_file(
                self._filename,
            )
        return self._config

    def set_filename(self, path: str) -> None:
        """Change the settings path and reload."""
        self._filename = path
        self._config = Config.from_file(
            filename=self._filename,
        )


configuration_dependency = ConfigurationDependency()
