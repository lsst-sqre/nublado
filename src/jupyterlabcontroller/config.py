"""Configuration definition."""

# This cannot be a dependency, because it is used by Uvicorn to set up
# logging before we have an app (which would own the dependency)

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict

import yaml

__all__ = [
    "Configuration",
    "config",
    "controller_config",
    "lab_config",
    "prepuller_config",
    "form_config",
]


@dataclass
class Configuration:
    """Configuration for jupyterlabcontroller."""

    name: str = os.getenv("SAFIR_NAME", "jupyterlab-controller")
    """The application's name (not the root HTTP endpoint path).

    Set with the ``SAFIR_NAME`` environment variable.
    """

    profile: str = os.getenv("SAFIR_PROFILE", "development")
    """Application run profile: "development" or "production".

    Set with the ``SAFIR_PROFILE`` environment variable.
    """

    logger_name: str = os.getenv("SAFIR_LOGGER", "jupyterlabcontroller")
    """The root name of the application's logger.

    Set with the ``SAFIR_LOGGER`` environment variable.
    """

    log_level: str = os.getenv("SAFIR_LOG_LEVEL", "INFO")
    """The log level of the application's logger.

    Set with the ``SAFIR_LOG_LEVEL`` environment variable.
    """

    k8s_request_timeout: int = int(os.getenv("K8S_REQUEST_TIMEOUT", "60"))
    """Timeout in seconds for Kubernetes API requests.

    Set with the ``K8s_REQUEST_TIMEOUT`` environment variable.
    """


config = Configuration()
"""Configuration for jupyterlab-controller."""

#
# We need to unify these two things.
#


_filename = "/etc/nublado/config.yaml"

controller_config: Dict[str, Any] = {}

with open(_filename) as f:
    controller_config = yaml.safe_load(f)

lab_config = controller_config["lab"]
prepuller_config = controller_config["prepuller"]
form_config = controller_config["form"]
