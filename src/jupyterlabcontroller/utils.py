import os
from copy import copy
from typing import Dict, List, Union

import bitmath

from ..models.v1.domain.config import Config
from ..models.v1.domain.labs import LabMap
from ..models.v1.external.userdata import UserQuota, UserQuotaQuantum

LIMIT_TO_REQUEST_RATIO: float = 4.0  # Seems to work well so far.

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


def check_for_user(username: str, labs: LabMap) -> bool:
    """True if there's a lab for the user, otherwise false."""
    return username in labs


def get_active_users(labs: LabMap) -> List[str]:
    """Returns a list of users with labs in 'running' state."""
    r: List[str] = []
    for u in labs:
        if labs[u].status == "running":
            r.append(u)
    return r


def get_user_namespace(username: str) -> str:
    return f"{username}-{get_namespace_prefix()}"


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


def quota_from_size(
    size: str, config: Config, ratio: float = LIMIT_TO_REQUEST_RATIO
) -> UserQuota:
    sizemap: Dict[
        str, Dict[str, Union[float, str]]
    ] = config.lab.sizes.to_dict()
    if size not in config.lab.sizes.keys():
        raise RuntimeError(f"Unknown size {size}")
    sz: Dict[str, Union[float, str]] = sizemap[size]
    cpu = float(sz["cpu"])
    memstr = str(sz["memory"])
    if not memstr.endswith("B"):
        memstr += "B"  # This makes bitmath happy
    mem: int = int(bitmath.parse_bytes(memstr).bytes)
    return UserQuota(
        requests=UserQuotaQuantum(cpu=cpu / ratio, mem=int(mem / ratio)),
        limits=UserQuotaQuantum(cpu=cpu, mem=mem),
    )
