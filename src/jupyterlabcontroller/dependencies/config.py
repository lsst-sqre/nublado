"""Configuration dependency."""
from typing import Optional

from ..models.v1.consts import CONFIGURATION_PATH
from ..models.v1.domain.config import Config


class ConfigurationDependency:
    _configuration_path: str = CONFIGURATION_PATH
    _config: Optional[Config] = None

    async def __call__(
        self,
    ) -> Config:
        return self.config()

    def config(self) -> Config:
        if self._config is None:
            self._config = Config.from_file(
                self._configuration_path,
            )
        return self._config

    def set_configuration_path(self, path: str) -> None:
        """Change the settings path and reload."""
        self._configuration_path = path
        self._config = Config.from_file(
            filename=self._configuration_path,
        )


configuration_dependency = ConfigurationDependency()
