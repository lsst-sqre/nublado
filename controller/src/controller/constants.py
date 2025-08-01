"""Global constants."""

from datetime import timedelta
from pathlib import Path

__all__ = [
    "ARGO_CD_ANNOTATIONS",
    "CONFIGURATION_PATH",
    "DOCKER_CREDENTIALS_PATH",
    "DROPDOWN_SENTINEL_VALUE",
    "GROUPNAME_REGEX",
    "KUBERNETES_NAME_PATTERN",
    "KUBERNETES_REQUEST_TIMEOUT",
    "LIMIT_TO_REQUEST_RATIO",
    "MEMORY_TO_TMP_SIZE_RATIO",
    "METADATA_PATH",
    "PREPULLER_POD_TIMEOUT",
    "RESERVED_ENV",
    "RESERVED_PATHS",
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

KUBERNETES_NAME_PATTERN = "^[a-z0-9]([-a-z0-9]*[a-z0-9])?$"
"""Pattern matching valid Kubernetes names."""

KUBERNETES_REQUEST_TIMEOUT = timedelta(seconds=30)
"""How long to wait for generic sequences of Kubernetes API calls.

Most Kubernetes API calls are part of a sequence of operations with an overall
timeout, but some are one-offs or one-off sequences. This timeout is used for
one-off operations, just to impose an upper limit on how long we'll wait of
the control plane is nonresponsive.
"""

JUPYTERLAB_DIR = "/usr/local/share/jupyterlab"
"""Location where our RSP Jupyterlab configuration is rooted."""

LAB_STOP_GRACE_PERIOD = timedelta(seconds=1)
"""How long to wait for a lab to shut down before SIGKILL.

Ideally we would let the lab shut down gracefully after SIGTERM with a longer
delay than this, but when we tried to do that in practice, a web browser open
to the lab spammed alert messages about missing files, presumably from the
JavaScript calls to the lab failing. Kubespawner uses a grace period of 1s and
appears to assume the lab will not do anything useful in repsonse to SIGTERM,
so copy its behavior.
"""

LIMIT_TO_REQUEST_RATIO = 4.0
"""Ratio of lab resource limits to requests.

The controller configuration only includes the Kubernetes limits. The resource
requests, which are the resources that must be aviailable for the lab to spawn
and which are used to determine autoscaling, are determined by dividing the
limits by this factor. Another way of looking at this value is that it's the
overcommit factor for labs, assuming many labs will not use their full
available resources.
"""

MEMORY_TO_TMP_SIZE_RATIO = 4.0
"""Ratio of maximum memory size to maximum size of :file:`/tmp` filesystem.

If :file:`tmp` is set to come out of pod memory, this obviously must be set to
a value greater than one.  If it comes out of disk it is ephemeral storage,
which is also sharply limited by node-local attached disk.
"""

METADATA_PATH = Path("/etc/podinfo")
"""Default path to injected pod metadata."""

PREPULLER_POD_TIMEOUT = timedelta(minutes=10)
"""How long to wait for a prepuller pod to spawn and finish running.

This may take a substantial amount of time if the pod image is quite large or
the network is slow.
"""

RESERVED_ENV = {
    "ACCESS_TOKEN",
    "DEBUG",
    "CONTAINER_SIZE",
    "CPU_GUARANTEE",
    "CPU_LIMIT",
    "EXTERNAL_INSTANCE_URL",
    "IMAGE_DIGEST",
    "IMAGE_DESCRIPTION",
    "JPY_API_TOKEN",
    "JUPYTER_IMAGE",
    "JUPYTER_IMAGE_SPEC",
    "KUBERNETES_NODE_NAME",
    "MEM_GUARANTEE",
    "MEM_LIMIT",
    "RESET_USER_ENV",
}
"""Environment variables reserved to the controller or JupyterHub.

These environment variables may not be set for labs in the Nublado controller
configuration since they must be set by the controller or by JupyterHub for
correct behavior. All environment variables starting with ``JUPYTERHUB_`` will
also be forbidden.
"""

RESERVED_PATHS = {"/etc/group", "/etc/passwd", "/tmp"}
"""Paths within the lab that are reserved for special purposes.

No files or volumes may be mounted over these paths.
"""

# These must be kept in sync with Gafaelfawr until we can import the models
# from Gafaelfawr directly.

GROUPNAME_REGEX = "^[a-zA-Z0-9][a-zA-Z0-9._-]*[a-zA-Z][a-zA-Z0-9._-]*$"
"""Regex matching all valid group names."""

USERNAME_REGEX = (
    "^[a-z0-9](?:[a-z0-9]|-[a-z0-9])*[a-z](?:[a-z0-9]|-[a-z0-9])*$"
)
"""Regex matching all valid usernames."""
