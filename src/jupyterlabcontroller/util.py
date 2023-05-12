"""General utility functions."""

from typing import Any

from kubernetes_asyncio.client import V1ObjectMeta


def deslashify(data: str) -> str:
    return data.replace("/", "_._")


def metadata_to_dict(metadata_object: V1ObjectMeta) -> dict[str, Any]:
    """Return the dict representation of a Kubernetes metadata object

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
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    str = ""
    if days:
        str = f"{days}d"
    if hours:
        str += f"{hours}h"
    if minutes:
        str += f"{minutes}m"
    if seconds:
        str += f"{seconds}s"
    return str
