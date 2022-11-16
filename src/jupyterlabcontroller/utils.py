import os
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


def get_user_namespace(username: str) -> str:
    return f"{get_namespace_prefix()}-{username}"


def get_namespace_prefix() -> str:
    """If USER_NAMESPACE_PREFIX is set in the environment, that will be used as
    the namespace prefix.  If it is not, the namespace will be read from the
    container.  If that file does not exist, "userlabs" will be used.
    """
    r: str = os.getenv("USER_NAMESPACE_PREFIX", "")
    if r:
        return r
    ns_path = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"
    if os.path.exists(ns_path):
        with open(ns_path) as f:
            return f.read().strip()
    return "userlabs"


def memory_string_to_int(memstr: str) -> int:
    if not memstr.endswith("B"):
        memstr += "B"  # This makes bitmath happy
    return int(bitmath.parse_string(memstr).bytes)
