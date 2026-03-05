"""Utility functions for starting LSST JupyterLab notebook environment."""

import os
from contextlib import suppress
from pathlib import Path
from typing import Any

from ..controller.models.domain.lab_configmap import LabConfigMap
from .constants import CONFIG_FILE

__all__ = [
    "get_access_token",
    "get_digest",
    "get_jupyterlab_config_dir",
    "get_runtime_mounts_dir",
    "load_config",
]


def get_access_token(
    tokenfile: str | Path | None = None, log: Any | None = None
) -> str:
    """Get the Gafaelfawr access token for the user.

    Determine the access token from the mounted location (nublado 3/2) or
    environment (any).  Prefer the mounted version since it can be updated,
    while the environment variable stays at whatever it was when the process
    was started.  Return the empty string if the token cannot be determined.
    """
    if tokenfile:
        return Path(tokenfile).read_text().strip()
    base_dir = get_runtime_mounts_dir()
    for candidate in (
        base_dir / "secrets" / "token",
        base_dir / "environment" / "ACCESS_TOKEN",
    ):
        with suppress(FileNotFoundError):
            return candidate.read_text().strip()

    # If we got here, we couldn't find a file. Return the environment variable
    # if set, otherwise the empty string.
    return os.environ.get("ACCESS_TOKEN", "")


def get_digest() -> str:
    """Return the digest of the current Docker image.

    Returns
    -------
    str
        Digest of the Docker image this code is running inside, or the empty
        string if the digest could not be determined.
    """
    return (load_config()).image.digest


def get_jupyterlab_config_dir() -> Path:
    """Return the directory where Jupyterlab configuration is stored.

    Returns
    -------
    pathlib.Path
        Location where Jupyterlab configuration is stored.
    """
    return Path((load_config()).jupyterlab_config_dir)


def get_runtime_mounts_dir() -> Path:
    """Return the directory where Nublado runtime info is mounted.

    Returns
    -------
    pathlib.Path
        Location where the Nublado runtime information is mounted.
    """
    return Path((load_config()).runtime_mounts_dir)


def load_config(cfile: Path = CONFIG_FILE) -> LabConfigMap:
    """Load the Nublado configuration data in the controller-made ConfigMap.

    Returns
    -------
    LabConfigMap
        Object representing sanitized Nublado configuration.
    """
    return LabConfigMap.model_validate_json(cfile.read_text())
