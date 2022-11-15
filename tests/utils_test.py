"""Tests for the jupyterlabcontroller.handlers.internal module and routes."""

from typing import Dict

from jupyterlabcontroller.config import Config
from jupyterlabcontroller.models.v1.lab import LabSize
from jupyterlabcontroller.utils import (
    get_namespace_prefix,
    get_user_namespace,
    memory_string_to_int,
    quota_from_size,
    std_annotations,
    std_labels,
)


def test_memory_string_to_int() -> None:
    assert memory_string_to_int("1k") == 1000
    assert memory_string_to_int("1kB") == 1000
    assert memory_string_to_int("1KiB") == 1024


def test_quota(config: Config) -> None:
    quota = quota_from_size(LabSize("medium"), config)
    assert quota.limits.memory == 6442450944
    assert quota.limits.cpu == 2.0
    assert quota.requests.memory == 1610612736
    assert quota.requests.cpu == 0.5


def test_labels() -> None:
    labels: Dict[str, str] = std_labels()
    assert labels["argocd.argoproj.io/instance"] == "nublado-users"


def test_annotations() -> None:
    annos: Dict[str, str] = std_annotations()
    assert annos["argocd.argoproj.io/compare-options"] == "IgnoreExtraneous"
    assert annos["argocd.argoproj.io/sync-options"] == "Prune=false"


def test_get_namespace_prefix() -> None:
    n = get_namespace_prefix()
    assert n == "userlabs"  # Will change if we're running in K8s...


def test_get_user_namespace() -> None:
    n = get_user_namespace("ribbon")
    assert n == "userlabs-ribbon"
