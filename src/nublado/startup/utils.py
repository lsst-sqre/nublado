"""Utility functions for LSST JupyterLab notebook environment."""

import os
from contextlib import suppress
from pathlib import Path
from typing import Any


def format_bytes(n: int) -> str:
    """Format bytes as text.

    Taken from ``dask.distributed``, where it is not exported.

    Examples
    --------
    >>> format_bytes(1)
    '1 B'
    >>> format_bytes(1234)
    '1.23 kB'
    >>> format_bytes(12345678)
    '12.35 MB'
    >>> format_bytes(1234567890)
    '1.23 GB'
    >>> format_bytes(1234567890000)
    '1.23 TB'
    >>> format_bytes(1234567890000000)
    '1.23 PB'
    """
    if n > 1e15:
        return f"{n / 1e15:0.2f} PB"
    if n > 1e12:
        return f"{n / 1e12:0.2f} TB"
    if n > 1e9:
        return f"{n / 1e9:0.2f} GB"
    if n > 1e6:
        return f"{n / 1e6:0.2f} MB"
    if n > 1e3:
        return f"{n / 1e3:0.2f} kB"
    return f"{n:d} B"


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
