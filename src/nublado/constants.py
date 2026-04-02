"""Constants for Nublado.  Overrideable for testing."""

from datetime import timedelta
from pathlib import Path

__all__ = [
    "ALERT_HOOK_ENV_VAR",
    "DOCKER_CREDENTIALS_PATH",
    "ENV_PREFIX",
    "GAR_RETRY_DELAY",
    "GAR_RETRY_LIMIT",
    "ROOT_LOGGER",
]

ENV_PREFIX = "NUBLADO"
"""Prefix for environment variables governing Nublado behavior."""

ALERT_HOOK_ENV_VAR = f"{ENV_PREFIX}_ALERT_HOOK"
"""Name of environment variable specifying Slack alert webhook."""

DOCKER_CREDENTIALS_PATH = Path("/etc/secrets/.dockerconfigjson")
"""Default path to the Docker API secrets."""

GAR_RETRY_DELAY = timedelta(seconds=10)
"""How long to wait between Google Artifact Registry retries."""

GAR_RETRY_LIMIT = 3
"""How many total times to attempt Google Artifact Registry calls."""

ROOT_LOGGER = "nublado"
"""Root logger name."""
