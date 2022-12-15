"""Constants for jupyterlab-controller
"""
import datetime
from pathlib import Path

CONFIGURATION_PATH = "/etc/nublado/config.yaml"
DOCKER_SECRETS_PATH = "/etc/secrets/.dockerconfigjson"

ADMIN_SCOPE = "admin:jupyterlab"
USER_SCOPE = "exec:notebook"

PREPULLER_DOCKER_POLL_INTERVAL = datetime.timedelta(minutes=5)
PREPULLER_K8S_POLL_INTERVAL = datetime.timedelta(minutes=1)
EPOCH = datetime.datetime.fromtimestamp(0, tz=datetime.timezone.utc)
# These are in seconds; they're arguments to various functions, not timedeltas.
KUBERNETES_REQUEST_TIMEOUT = 60
PREPULLER_PULL_TIMEOUT = 600
PREPULLER_INTERNAL_POLL_PERIOD = 1.0

LIMIT_TO_REQUEST_RATIO: float = 4.0  # Seems to work well so far.

with open(str(Path(__file__).parent / "assets" / "form_template.txt")) as f:
    SPAWNER_FORM_TEMPLATE = f.read()
