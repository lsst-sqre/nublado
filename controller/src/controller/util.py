"""General utility functions."""

from __future__ import annotations

from typing import Any

from kubernetes_asyncio.client import V1ObjectMeta

__all__ = [
    "deslashify",
    "metadata_to_dict",
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
