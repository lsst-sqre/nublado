"""Global constants."""

from datetime import timedelta
from pathlib import Path

__all__ = [
    "CONFIGURATION_PATH",
    "DOCKER_SECRETS_PATH",
    "DROPDOWN_SENTINEL_VALUE",
    "GROUPNAME_REGEX",
    "IMAGE_REFRESH_INTERVAL",
    "KUBERNETES_REQUEST_TIMEOUT",
    "LAB_STATE_REFRESH_INTERVAL",
    "LIMIT_TO_REQUEST_RATIO",
    "METADATA_PATH",
    "SPAWNER_FORM_TEMPLATE",
    "USERNAME_REGEX",
]

CONFIGURATION_PATH = Path("/etc/nublado/config.yaml")
"""Default path to controller configuration."""

DOCKER_SECRETS_PATH = Path("/etc/secrets/.dockerconfigjson")
"""Default path to the Docker API secrets."""

DROPDOWN_SENTINEL_VALUE = "use_image_from_dropdown"
"""Used in the lab form for ``image_list`` when ``image_dropdown`` is used."""

IMAGE_REFRESH_INTERVAL = timedelta(minutes=5)
"""How frequently to refresh the list of remote and cached images."""

LAB_STATE_REFRESH_INTERVAL = timedelta(minutes=60)
"""How frequently to refresh user lab state from Kubernetes.

This will detect when user labs disappear out from under us without user
action, such as labs being terminated by Kubernetes node replacements or
upgrades.
"""

METADATA_PATH = Path("/etc/podinfo")
"""Default path to injected pod metadata."""

FILESERVER_RECONCILIATION_INTERVAL = timedelta(minutes=2)
"""How frequently to refresh the fileserver map against Kubernetes."""

# These are in seconds; they're arguments to various functions, not timedeltas.
KUBERNETES_REQUEST_TIMEOUT = 60

LIMIT_TO_REQUEST_RATIO: float = 4.0  # Seems to work well so far.

SPAWNER_FORM_TEMPLATE = (
    Path(__file__).parent / "assets" / "form_template.txt"
).read_text()

FILESERVER_TEMPLATE = (
    Path(__file__).parent / "assets" / "fileserver_template.txt"
).read_text()

# These must be kept in sync with Gafaelfawr until we can import the models
# from Gafaelfawr directly.

GROUPNAME_REGEX = "^[a-zA-Z][a-zA-Z0-9._-]*$"
"""Regex matching all valid group names."""

USERNAME_REGEX = (
    "^[a-z0-9](?:[a-z0-9]|-[a-z0-9])*[a-z](?:[a-z0-9]|-[a-z0-9])*$"
)
"""Regex matching all valid usernames."""

# User file servers
FILESERVER_NAMESPACE = "fileservers"
"""Default name of namespace that contains user file servers."""
