"""Configuration dependency."""
from typing import Any, Dict

import yaml

from ..models.v1.domain.config import Config


class ConfigurationDependency:
    async def __call__(self) -> Config:
        _filename = "/etc/nublado/config.yaml"

        config_obj: Dict[str, Any] = {}
        with open(_filename) as f:
            config_obj = yaml.safe_load(f)
            return Config.parse_obj(config_obj)


configuration_dependency = ConfigurationDependency()
