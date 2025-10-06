"""Tests for filtering architecture-specific image tags."""

from controller.models.domain.arch_filter import filter_arch_tags


def test_arch_filter() -> None:
    tags = [
        "recommended",
        "w_2025_39",
        "w_2025_39-amd64",
        "w_2025_39-arm64",
        "w_2025_40-arm64",
    ]
    filtered = filter_arch_tags(tags)
    assert filtered == ["recommended", "w_2025_39", "w_2025_40-arm64"]
