"""Configuration definition."""

from __future__ import annotations

import os
from dataclasses import dataclass

__all__ = ["Configuration", "config"]


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
