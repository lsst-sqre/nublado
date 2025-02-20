"""Tests of Docker image tag parsing and analysis."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from random import SystemRandom

from semver import Version

from controller.models.domain.imagefilterpolicy import (
    ImageFilterPolicy,
    RSPImageFilterPolicy,
)
from controller.models.domain.rsptag import (
    RSPImageTagCollection,
)


def test_imagefilter() -> None:
    """Test behavior of an RSPImageTagCollection object under a filter."""
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
    age_basis = datetime(2025, 2, 19, 17, tzinfo=UTC)
    # This is week 8, weekday 3.  w_2025_08 does not yet exist.

    shuffled_tags = list(tags)
    SystemRandom().shuffle(shuffled_tags)

    recommended = {"recommended"}
    collection = RSPImageTagCollection.from_tag_names(
        shuffled_tags, recommended
    )

    assert len(list(collection.all_tags())) == len(tags)

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

    filtered_tags = [
        x.tag for x in list(collection.filter(policy, age_basis).all_tags())
    ]

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
