"""Global constants."""

from datetime import timedelta
from pathlib import Path

CONFIGURATION_PATH = Path("/etc/nublado/config.yaml")
"""Default path to controller configuration."""

DOCKER_SECRETS_PATH = Path("/etc/secrets/.dockerconfigjson")
"""Default path to the Docker API secrets."""

IMAGE_REFRESH_INTERVAL = timedelta(minutes=5)
"""How frequently to refresh the list of remote and cached images."""

ADMIN_SCOPE = "admin:jupyterlab"
USER_SCOPE = "exec:notebook"

DROPDOWN_SENTINEL_VALUE = "use_image_from_dropdown"

# These are in seconds; they're arguments to various functions, not timedeltas.
KUBERNETES_REQUEST_TIMEOUT = 60

LIMIT_TO_REQUEST_RATIO: float = 4.0  # Seems to work well so far.

SPAWNER_FORM_TEMPLATE = (
    Path(__file__).parent / "assets" / "form_template.txt"
).read_text()
