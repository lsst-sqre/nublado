"""Constants for rsp-scratchpurger.  Overrideable for testing."""

from pathlib import Path

CONFIG_FILE = Path("/etc/purger/config.yaml")
ENV_PREFIX = "RSP_SCRATCHPURGER_"
ALERT_HOOK_ENV_VAR = f"{ENV_PREFIX}ALERT_HOOK"
CONFIG_FILE_ENV_VAR = f"{ENV_PREFIX}CONFIG_FILE"
POLICY_FILE = Path("/etc/purger/policy.yaml")
ROOT_LOGGER = "rsp_scratchpurger"
