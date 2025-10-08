"""Tests for filtering architecture-specific image tags."""

from controller.models.domain.arch_filter import (
    filter_arch_images,
    filter_arch_tags,
)
from controller.models.domain.rspimage import RSPImage
from controller.models.domain.rsptag import RSPImageTag


def test_arch_filter_tags() -> None:
    tags = [
        "recommended",
        "w_2025_39",
        "w_2025_39-amd64",
        "w_2025_39-arm64",
        "w_2025_40-arm64",
    ]
    filtered = filter_arch_tags(tags)
    assert filtered == ["recommended", "w_2025_39", "w_2025_40-arm64"]


def test_arch_filter_images() -> None:
    tags = [
        "recommended",
        "w_2025_39",
        "w_2025_39-amd64",
        "w_2025_39-arm64",
        "w_2025_40-arm64",
    ]

    rsptags = [RSPImageTag.from_str(x) for x in tags]
    rspimages = [
        RSPImage.from_tag(
            registry="ghcr.io",
            repository="lsst-sqre/sciplat-lab",
            tag=x,
            digest="sha256:abcd",
        )
        for x in rsptags
    ]

    filtered = filter_arch_images(rspimages)
    filtered_tags = [x.tag for x in filtered]
    assert filtered_tags == ["recommended", "w_2025_39", "w_2025_40-arm64"]
