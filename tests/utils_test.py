"""Tests for the jupyterlabcontroller.handlers.internal module and routes."""

from typing import Dict

from jupyterlabcontroller.utils import (
    memory_string_to_int,
    std_annotations,
    std_labels,
)


def test_memory_string_to_int() -> None:
    assert memory_string_to_int("1k") == 1000
    assert memory_string_to_int("1kB") == 1000
    assert memory_string_to_int("1KiB") == 1024


def test_labels() -> None:
    labels: Dict[str, str] = std_labels()
    assert labels["argocd.argoproj.io/instance"] == "nublado-users"


def test_annotations() -> None:
    annos: Dict[str, str] = std_annotations()
    assert annos["argocd.argoproj.io/compare-options"] == "IgnoreExtraneous"
    assert annos["argocd.argoproj.io/sync-options"] == "Prune=false"
