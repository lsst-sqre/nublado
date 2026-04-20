"""Constants for rsp-scratchpurger.  Overrideable for testing."""

from pathlib import Path

__all__ = [
    "ALERT_HOOK_ENV_VAR",
    "CONFIG_FILE",
    "CONFIG_FILE_ENV_VAR",
    "ENV_PREFIX",
    "POLICY_FILE",
    "ROOT_LOGGER",
]

CONFIG_FILE = Path("/etc/purger/config.yaml")
ENV_PREFIX = "RSP_SCRATCHPURGER_"
ALERT_HOOK_ENV_VAR = f"{ENV_PREFIX}ALERT_HOOK"
CONFIG_FILE_ENV_VAR = f"{ENV_PREFIX}CONFIG_FILE"
POLICY_FILE = Path("/etc/purger/policy.yaml")
ROOT_LOGGER = "rsp_scratchpurger"
