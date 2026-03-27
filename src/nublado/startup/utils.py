"""Utility functions for starting LSST JupyterLab notebook environment."""

import os
from pathlib import Path

__all__ = [
    "get_digest",
    "get_jupyterlab_config_dir",
    "get_runtime_mounts_dir",
]


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
