from copy import copy
from typing import Dict

import bitmath

__all__ = ["std_annotations", "std_labels"]

_std_annotations = {
    "argocd.argoproj.io/compare-options": "IgnoreExtraneous",
    "argocd.argoproj.io/sync-options": "Prune=false",
}

_std_labels = {"argocd.argoproj.io/instance": "nublado-users"}


def std_annotations() -> Dict[str, str]:
    return copy(_std_annotations)


def std_labels() -> Dict[str, str]:
    return copy(_std_labels)


def memory_string_to_int(memstr: str) -> int:
    if not memstr.endswith("B"):
        memstr += "B"  # This makes bitmath happy
    return int(bitmath.parse_string(memstr).bytes)
