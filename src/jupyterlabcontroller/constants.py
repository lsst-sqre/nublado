"""Global constants."""

from datetime import timedelta
from pathlib import Path

__all__ = [
    "CONFIGURATION_PATH",
    "DOCKER_SECRETS_PATH",
    "DROPDOWN_SENTINEL_VALUE",
    "GROUPNAME_REGEX",
    "IMAGE_REFRESH_INTERVAL",
    "KUBERNETES_DELETE_TIMEOUT",
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

KUBERNETES_DELETE_TIMEOUT = timedelta(seconds=60)
"""How long to wait for deletion of an object to finish.

In some cases, if a Kubernetes object the controller is trying to create
already exists, it deletes that object and then retries the creation. This
controls how long it waits for the object to go away after deletion before it
gives up.
"""

LAB_STATE_REFRESH_INTERVAL = timedelta(minutes=60)
"""How frequently to refresh user lab state from Kubernetes.

This will detect when user labs disappear out from under us without user
action, such as labs being terminated by Kubernetes node replacements or
upgrades.
"""

LAB_STOP_GRACE_PERIOD = timedelta(seconds=1)
"""How long to wait for a lab to shut down before SIGKILL.

Ideally we would let the lab shut down gracefully after SIGTERM with a longer
delay than this, but when we tried to do that in practice, a web browser open
to the lab spammed alert messages about missing files, presumably from the
JavaScript calls to the lab failing. Kubespawner uses a grace period of 1s and
appears to assume the lab will not do anything useful in repsonse to SIGTERM,
so copy its behavior.
"""

METADATA_PATH = Path("/etc/podinfo")
"""Default path to injected pod metadata."""

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
