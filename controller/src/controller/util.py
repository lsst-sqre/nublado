"""General utility functions."""

from __future__ import annotations

from typing import Any

from kubernetes_asyncio.client import V1ObjectMeta

__all__ = [
    "deslashify",
    "metadata_to_dict",
    "seconds_to_phrase",
]


def deslashify(data: str) -> str:
    """Replace slashes with ``_._`` to form valid Kubernetes identifiers."""
    return data.replace("/", "_._")


def metadata_to_dict(metadata_object: V1ObjectMeta) -> dict[str, Any]:
    """Return the dict representation of a Kubernetes metadata object.

    Parameters
    ----------
    metadata_object
        a V1ObjectMeta Kubernetes metadata object

    Returns
    -------
    Dict[str,Any]
        Python dict representation of the metadata object.  Used for
        custom resources, which require dicts rather than Kubernetes
        objects.
    """
    md_obj = {
        "name": metadata_object.name,
        "annotations": metadata_object.annotations,
        "labels": metadata_object.labels,
    }
    if metadata_object.namespace:
        md_obj["namespace"] = metadata_object.namespace
    return md_obj


def seconds_to_phrase(seconds: int) -> str:
    """Format seconds as a human-readable string.

    Parameters
    ----------
    seconds
        Duration in seconds.

    Returns
    -------
    str
        Human-readable equivalent using ``d`` for days, ``h`` for hours, ``m``
        for minutes, and ``s`` for seconds. Daylight saving time transitions
        are not taken into account.
    """
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    string = ""
    if days:
        string = f"{days}d"
    if hours:
        string += f"{hours}h"
    if minutes:
        string += f"{minutes}m"
    if seconds:
        string += f"{seconds}s"
    return string
