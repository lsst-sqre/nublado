"""Tests of Docker image tag parsing and analysis."""

from datetime import UTC, datetime, timedelta
from random import SystemRandom

from semver import Version

from nublado.models.images import (
    ImageFilter,
    ImageFilterPolicy,
    RSPImageTagCollection,
)


def test_filter() -> None:
    """Test behavior of an RSPImageTagCollection object under a filter."""
    tags = [
        "recommended",
        "recommended-amd64",
        "r28_0_1",
        "r28_0_1-amd64",
        "r28_0_0",
        "r27_0_0",
        "r26_0_0",
        "w_2025_07",
        "w_2025_07-arm64",
        "w_2025_06",
        "w_2025_05",
        "w_2025_04",
        "d_2025_02_19",
        "d_2025_02_18",
        "d_2025_02_17",
        "d_2025_02_16",
        "r28_0_0_rc2-amd64",
        "r28_0_0_rc1",
        "r27_0_0_rc1",
        "exp_w_2025_07",
        "exp_w_2025_06",
        "exp_w_2025_05",
        "unknown",
    ]
    SystemRandom().shuffle(tags)

    # This is week 8, weekday 3. w_2025_08 does not yet exist.
    age_basis = datetime(2025, 2, 19, 17, tzinfo=UTC)

    # Build the collection.
    recommended = {"recommended", "recommended-amd64"}
    collection = RSPImageTagCollection.from_tag_names(tags, recommended)

    # Create image policy. This should return three releases, two weeklies,
    # two dailies (due to the age policy; the number policy will have no
    # effect), one release candidate (from the number policy, version will
    # have no effect), and one experimental.
    policy = ImageFilterPolicy(
        release=ImageFilter(
            cutoff_version=Version(major=27, minor=0, patch=0)
        ),
        weekly=ImageFilter(age=timedelta(weeks=2)),
        daily=ImageFilter(age=timedelta(days=2), number=4),
        release_candidate=ImageFilter(
            cutoff_version=Version(major=25, minor=3, patch=1), number=1
        ),
        experimental=ImageFilter(cutoff_date=datetime(2025, 2, 7, tzinfo=UTC)),
    )

    # We should also get the alias tag and the unknown tag, first and last
    # respectively.
    filtered_tags = [x.tag for x in collection.filter(policy, age_basis)]
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

    # Redo the filtering without excluding arch-specific images (the
    # non-default mode). Version- and date-based filtering should just include
    # the new images. Count-based filtering will push a different image off.
    filtered_tags = [
        x.tag
        for x in collection.filter(
            policy, age_basis, remove_arch_specific=False
        )
    ]
    assert filtered_tags == [
        "recommended",
        "recommended-amd64",
        "r28_0_1",
        "r28_0_1-amd64",
        "r28_0_0",
        "r27_0_0",
        "w_2025_07",
        "w_2025_07-arm64",
        "w_2025_06",
        "d_2025_02_19",
        "d_2025_02_18",
        "r28_0_0_rc2-amd64",
        "exp_w_2025_07",
        "unknown",
    ]


def test_filter_semver() -> None:
    tags = [
        "r28_0_1",
        "r28_0_0",
        "w_2025_07",
        "w_2025_06",
        "r28_0_2_rc1",
        "r27_0_1_rc1",
        "exp_w_2025_07",
        "exp_r28_0_1_exp",
        "exp_r28_0_0_exp",
    ]
    collection = RSPImageTagCollection.from_tag_names(tags, set())

    # Construct a filter that uses 28.0.1 as a semantic version cutoff. This
    # should have no effect on the weeklies but should affect the experimental
    # tags.
    cutoff_version = Version(major=28, minor=0, patch=1)
    policy = ImageFilterPolicy(
        release=ImageFilter(cutoff_version=cutoff_version),
        release_candidate=ImageFilter(cutoff_version=cutoff_version),
        weekly=ImageFilter(cutoff_version=cutoff_version),
        experimental=ImageFilter(cutoff_version=cutoff_version),
    )

    # Run the filter and check the results. The age basis shouldn't matter.
    now = datetime.now(tz=UTC)
    filtered_tags = [x.tag for x in collection.filter(policy, now)]
    assert filtered_tags == [
        "r28_0_1",
        "w_2025_07",
        "w_2025_06",
        "r28_0_2_rc1",
        "exp_w_2025_07",
        "exp_r28_0_1_exp",
    ]
