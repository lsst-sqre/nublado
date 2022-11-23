"""Constants for jupyterlab-controller
"""
from pathlib import Path

CONFIGURATION_PATH = "/etc/nublado/config.yaml"
DOCKER_SECRETS_PATH = "/etc/secrets/.dockerconfigjson"

ADMIN_SCOPE = "admin:jupyterlab"
USER_SCOPE = "exec:notebook"

KUBERNETES_REQUEST_TIMEOUT: int = 60

PREPULLER_POLL_INTERVAL: int = 60
PREPULLER_PULL_TIMEOUT: int = 600

LIMIT_TO_REQUEST_RATIO: float = 4.0  # Seems to work well so far.

with open(str(Path(__file__).parent / "assets" / "form_template.txt")) as f:
    SPAWNER_FORM_TEMPLATE = f.read()
