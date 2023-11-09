"""Global constants."""

from datetime import timedelta
from pathlib import Path

__all__ = [
    "ARGO_CD_ANNOTATIONS",
    "CONFIGURATION_PATH",
    "DOCKER_CREDENTIALS_PATH",
    "DROPDOWN_SENTINEL_VALUE",
    "GROUPNAME_REGEX",
    "FILE_SERVER_REFRESH_INTERVAL",
    "IMAGE_REFRESH_INTERVAL",
    "KUBERNETES_DELETE_TIMEOUT",
    "KUBERNETES_REQUEST_TIMEOUT",
    "LAB_COMMAND",
    "LAB_STATE_REFRESH_INTERVAL",
    "LIMIT_TO_REQUEST_RATIO",
    "METADATA_PATH",
    "MOUNT_PATH_DOWNWARD_API",
    "MOUNT_PATH_ENVIRONMENT",
    "MOUNT_PATH_SECRETS",
    "PREPULLER_POD_TIMEOUT",
    "USERNAME_REGEX",
]

ARGO_CD_ANNOTATIONS = {
    "argocd.argoproj.io/compare-options": "IgnoreExtraneous",
    "argocd.argoproj.io/sync-options": "Prune=false",
}
"""Annotations to add to most created objects.

These annotations tell Argo CD to ignore these resources for the purposes of
determining if the Argo Cd ``Application`` object is out of date. We apply
them to all the resources managed by the Nublado controller, since Argo CD
should not manage them.
"""

CONFIGURATION_PATH = Path("/etc/nublado/config.yaml")
"""Default path to controller configuration."""

DOCKER_CREDENTIALS_PATH = Path("/etc/secrets/.dockerconfigjson")
"""Default path to the Docker API secrets."""

DROPDOWN_SENTINEL_VALUE = "use_image_from_dropdown"
"""Used in the lab form for ``image_list`` when ``image_dropdown`` is used."""

FILE_SERVER_REFRESH_INTERVAL = timedelta(minutes=60)
"""How frequently to refresh file server state from Kubernetes.

This will detect when file servers disappear out from under us, such as being
terminated by Kubernetes node replacements or upgrades.
"""

IMAGE_REFRESH_INTERVAL = timedelta(minutes=5)
"""How frequently to refresh the list of remote and cached images."""

KUBERNETES_DELETE_TIMEOUT = timedelta(seconds=60)
"""How long to wait for deletion of an object to finish.

In some cases, if a Kubernetes object the controller is trying to create
already exists, it deletes that object and then retries the creation. This
controls how long it waits for the object to go away after deletion before it
gives up.
"""

LAB_COMMAND = "/opt/lsst/software/jupyterlab/runlab.sh"
"""Command used to start the lab.

This should be configurable but isn't yet.
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

MOUNT_PATH_DOWNWARD_API = "/opt/lsst/software/jupyterlab/runtime"
"""Path at which downward API information is mounted inside the lab.

This should be configurable but isn't yet.
"""

MOUNT_PATH_ENVIRONMENT = "/opt/lsst/software/jupyterlab/environment"
"""Path at which the environment for the user is mounted inside the lab.

This should be configurable but isn't yet.
"""

MOUNT_PATH_SECRETS = "/opt/lsst/software/jupyterlab/secrets"
"""Path at which secrets are mounted inside the lab.

This should be configurable but isn't yet.
"""

PREPULLER_POD_TIMEOUT = timedelta(minutes=10)
"""How long to wait for a prepuller pod to spawn and finish running.

This may take a substantial amount of time if the pod image is quite large or
the network is slow.
"""

# These are in seconds; they're arguments to various functions, not timedeltas.
KUBERNETES_REQUEST_TIMEOUT = 60

LIMIT_TO_REQUEST_RATIO: float = 4.0  # Seems to work well so far.

# These must be kept in sync with Gafaelfawr until we can import the models
# from Gafaelfawr directly.

GROUPNAME_REGEX = "^[a-zA-Z][a-zA-Z0-9._-]*$"
"""Regex matching all valid group names."""

USERNAME_REGEX = (
    "^[a-z0-9](?:[a-z0-9]|-[a-z0-9])*[a-z](?:[a-z0-9]|-[a-z0-9])*$"
)
"""Regex matching all valid usernames."""
