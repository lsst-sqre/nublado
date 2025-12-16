"""Utility functions for starting LSST JupyterLab notebook environment."""

import os
from contextlib import suppress
from pathlib import Path
from typing import Any

__all__ = [
    "get_access_token",
    "get_digest",
    "get_jupyterlab_config_dir",
    "get_runtime_mounts_dir",
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
    spec = os.environ.get("JUPYTER_IMAGE_SPEC", "")
    hash_marker = "@sha256:"
    hash_pos = spec.find(hash_marker)
    if hash_pos == -1:
        return ""
    return spec[hash_pos + len(hash_marker) :]


def get_jupyterlab_config_dir() -> Path:
    """Return the directory where Jupyterlab configuration is stored.
    For single-python images, this will be `/opt/lsst/software/jupyterlab`.

    For images with split stack and Jupyterlab Pythons, it will be the
    value of `JUPYTERLAB_CONFIG_DIR`.

    Returns
    -------
    pathlib.Path
        Location where Jupyterlab configuration is stored.
    """
    return Path(
        os.environ.get(
            "JUPYTERLAB_CONFIG_DIR", "/opt/lsst/software/jupyterlab"
        )
    )


def get_runtime_mounts_dir() -> Path:
    """Return the directory where Nublado runtime info is mounted.  For
    single-python images, this will be `/opt/lsst/software/jupyterlab`.

    For images with split stack and Jupyterlab Pythons, it will be the
    value of `NUBLADO_RUNTIME_MOUNTS_DIR`.

    Returns
    -------
    pathlib.Path
        Location where the Nublado runtime information is mounted.
    """
    return Path(
        os.environ.get(
            "NUBLADO_RUNTIME_MOUNTS_DIR", "/opt/lsst/software/jupyterlab"
        )
    )
