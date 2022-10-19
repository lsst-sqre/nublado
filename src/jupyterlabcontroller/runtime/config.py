from typing import Any, Dict

import yaml

_filename = "/etc/nublado/config.yaml"

__all__ = ["controller_config"]

controller_config: Dict[str, Any] = {}

with open(_filename) as f:
    controller_config = yaml.safe_load(f)
