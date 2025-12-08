"""Constants for Nublado.  Overrideable for testing."""

__all__ = ["ALERT_HOOK_ENV_VAR", "ENV_PREFIX", "ROOT_LOGGER"]

ENV_PREFIX = "NUBLADO"
"""Prefix for environment variables governing Nublado behavior."""

ALERT_HOOK_ENV_VAR = f"{ENV_PREFIX}_ALERT_HOOK"
"""Name of environment variable specifying Slack alert webhook."""

ROOT_LOGGER = "nublado"
"""Root logger name."""
