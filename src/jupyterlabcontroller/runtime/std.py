from typing import Dict

__all__ = ["std_annotations", "std_labels"]

_std_annotations = {
    "argocd.argoproj.io/compare-options": "IgnoreExtraneous",
    "argocd.argoproj.io/sync-options": "Prune=false",
}

_std_labels = {"argocd.argoproj.io/instance": "nublado-users"}


def std_annotations() -> Dict[str, str]:
    return {}.update(_std_annotations)


def std_labels() -> Dict[str, str]:
    return {}.update(_std_labels)
