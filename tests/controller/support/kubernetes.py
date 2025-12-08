"""Support functions for Kubernetes tests."""

from __future__ import annotations

from typing import Any

from safir.testing.kubernetes import strip_none

from nublado.controller.models.domain.kubernetes import KubernetesModel

__all__ = [
    "objects_to_dicts",
]


def objects_to_dicts(
    objects: list[dict | KubernetesModel],
) -> list[dict[str, Any]]:
    """Serialize a list of Kubernetes objects for comparison.

    We often want to compare the contents of the mock Kubernetes with the
    expected objects we were hoping to create from, for example, a JSON file.
    This function handles the complexities of that serialization.

    Parameters
    ----------
    objects
        List of objects to serialize, which may include custom objects that
        are represented by raw dicts.

    Returns
    -------
    list of dict
        List of serialized objects with `None` elements removed, suitable
        for comparison.
    """
    results = []
    for obj in objects:
        if isinstance(obj, dict):
            serialized = obj
        else:
            serialized = obj.to_dict(serialize=True)

        # These attributes intentionally may change on every test run and thus
        # should not be compared.
        serialized["metadata"]["resourceVersion"] = None
        if "status" in serialized and serialized["status"] is not None:
            serialized["status"]["startTime"] = None

        results.append(strip_none(serialized))
    return results
