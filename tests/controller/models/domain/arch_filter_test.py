"""Tests for filtering architecture-specific image tags."""

from datetime import UTC, datetime, timedelta
from random import SystemRandom

from semver import Version

from nublado.controller.models.domain.arch_filter import (
    filter_arch_images,
    filter_arch_tags,
)
from nublado.controller.models.domain.imagefilterpolicy import (
    ImageFilterPolicy,
    RSPImageFilterPolicy,
)
from nublado.controller.models.domain.rspimage import RSPImage
from nublado.controller.models.domain.rsptag import (
    RSPImageTag,
    RSPImageTagCollection,
)


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


def test_image_and_arch_filter() -> None:
    """Test behavior of an RSPImageTagCollection object under both arch and
    quantity filter.
    """
    tags = [
        "recommended",
        "r28_0_1",
        "r28_0_0",
        "r27_0_0",
        "r26_0_0",
        "w_2025_07",
        "w_2025_06",
        "w_2025_05",
        "w_2025_04",
        "d_2025_02_19",
        "d_2025_02_18",
        "d_2025_02_17",
        "d_2025_02_16",
        "r28_0_0_rc1",
        "r27_0_0_rc1",
        "exp_w_2025_07",
        "exp_w_2025_06",
        "exp_w_2025_05",
        "unknown",
    ]
    tags.extend([f"{x}-{arch}" for x in tags for arch in ("amd64", "arm64")])
    age_basis = datetime(2025, 2, 19, 17, tzinfo=UTC)
    # This is week 8, weekday 3.  w_2025_08 does not yet exist.

    shuffled_tags = list(tags)
    SystemRandom().shuffle(shuffled_tags)

    recommended = {"recommended"}
    collection = RSPImageTagCollection.from_tag_names(
        shuffled_tags, recommended
    )

    all_tags = list(collection.all_tags())
    assert len(all_tags) == len(tags)

    # Create

    filtered_tags = filter_arch_tags([x.tag for x in all_tags])

    flt_collection = RSPImageTagCollection.from_tag_names(
        filtered_tags, recommended
    )

    # Create image policy

    policy = RSPImageFilterPolicy(
        release=ImageFilterPolicy(
            # We should get three
            cutoff_version=str(Version(major=27, minor=0, patch=0))
        ),
        weekly=ImageFilterPolicy(
            # We should get two
            age=timedelta(weeks=2)
        ),
        daily=ImageFilterPolicy(
            # We should get two from the age policy: number will never be
            # the filter.
            age=timedelta(days=2),
            number=4,
        ),
        release_candidate=ImageFilterPolicy(
            # We should only get one, not two: number will be the filter
            cutoff_version=str(Version(major=25, minor=3, patch=1)),
            number=1,
        ),
        experimental=ImageFilterPolicy(
            # We should get one.  We'll use calver, which because the
            # experimental is built from a weekly, should work fine.
            cutoff_version=str(Version(major=2025, minor=7, patch=0))
        ),
    )
    # We should also get the alias tag and the unknown tag, first and last
    # respectively.

    filtered_tags = [x.tag for x in flt_collection.filter(policy, age_basis)]

    assert filtered_tags == [
        "recommended",
        "r28_0_1",
        "r28_0_0",
        "r27_0_0",
        "w_2025_07",
        "w_2025_06",
        "d_2025_02_19",
        "d_2025_02_18",
        "r28_0_0_rc1",
        "exp_w_2025_07",
        "unknown",
    ]


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
