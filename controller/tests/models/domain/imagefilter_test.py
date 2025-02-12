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
    RSPImageType,
)


def test_imagefilter() -> None:
    """Test behavior of an RSPImageTagCollection object under a filter."""

    # Make some weekly and daily tags.  Because we can run this test at
    # an arbitrary time...we need to dynamically generate these.
    def to_weekly_tag(dt: datetime) -> str:
        ic = dt.isocalendar()
        icy = str(ic.year).zfill(2)
        icw = str(ic.week).zfill(2)
        return f"w_{icy}_{icw}"

    def to_daily_tag(dt: datetime) -> str:
        mo = str(dt.month).zfill(2)
        dy = str(dt.day).zfill(2)
        return f"d_{dt.year}_{mo}_{dy}"

    # Because image ages are calculated based on the tags, and are
    # therefore calculated as if they were born at midnight UTC, you
    # might have one fewer image than you expect in a category depending
    # on local time if you're west of UTC, or one more if you're east of UTC.
    #
    # In practice, people will set age-based limits fairly high and
    # few people will be using the dropdown anyway, so the practical
    # effect is minimal.  However, it does make for more difficult testing.
    #
    # What we're going to do is pick ranges so we will have from one to three
    # tags in the resulting range, and then check to make sure the middle one
    # is always present, which it should be.

    now = datetime.now(tz=UTC)

    last_week = now - timedelta(days=7)
    two_weeks_ago = now - timedelta(days=14)
    three_weeks_ago = now - timedelta(days=21)

    yesterday = now - timedelta(days=1)
    day_before_yesterday = now - timedelta(days=2)
    three_days_ago = now - timedelta(days=3)

    tag_this_week = to_weekly_tag(now)
    tag_last_week = to_weekly_tag(last_week)
    tag_two_weeks_ago = to_weekly_tag(two_weeks_ago)
    tag_three_weeks_ago = to_weekly_tag(three_weeks_ago)

    tag_today = to_daily_tag(now)
    tag_yesterday = to_daily_tag(yesterday)
    tag_day_before_yesterday = to_daily_tag(day_before_yesterday)
    tag_three_days_ago = to_daily_tag(three_days_ago)

    exp_tag_this_week = f"exp_{tag_this_week}"
    exp_tag_last_week = f"exp_{tag_last_week}"
    exp_tag_two_weeks_ago = f"exp_{tag_two_weeks_ago}"

    tags = [
        "recommended",
        "r28_0_1",
        "r28_0_0",
        "r27_0_0",
        "r26_0_0",
        tag_this_week,
        tag_last_week,
        tag_two_weeks_ago,
        tag_three_weeks_ago,
        tag_today,
        tag_yesterday,
        tag_day_before_yesterday,
        tag_three_days_ago,
        "r28_0_0_rc1",
        "r27_0_0_rc1",
        exp_tag_this_week,
        exp_tag_last_week,
        exp_tag_two_weeks_ago,
        "unknown",
    ]

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
            # We should get one, two, or three
            age=timedelta(weeks=2)
        ),
        daily=ImageFilterPolicy(
            # We should get one, two, or three from the age policy,
            # but definitely not four: number will never be the filter
            age=timedelta(days=2),
            number=4,
        ),
        release_candidate=ImageFilterPolicy(
            # We should only get one, not two: number will be the filter
            cutoff_version=str(Version(major=25, minor=3, patch=1)),
            number=1,
        ),
        experimental=ImageFilterPolicy(
            # We should get one, two or three.  For
            # dated releases we use calver
            cutoff_version=str(
                Version(
                    major=last_week.isocalendar().year,
                    minor=last_week.isocalendar().week,
                    patch=0,
                )
            )
        ),
    )

    filtered = collection.apply_policy(policy)

    # We should lead off with one alias image not accounted for by the
    # policy.  The unknown tag should be filtered out.

    total_len = len(list(filtered.all_tags()))

    # These account for the timezone fuzz.
    #                   A   R   W   D   C   X   U
    assert total_len >= 1 + 3 + 1 + 1 + 1 + 1 + 0  # West of UTC
    assert total_len <= 1 + 3 + 3 + 3 + 1 + 3 + 0  # East of UTC

    alias_tags = [
        x.tag for x in list(filtered.by_type(RSPImageType.ALIAS).all_tags())
    ]
    assert alias_tags == ["recommended"]

    release_tags = [
        x.tag for x in list(filtered.by_type(RSPImageType.RELEASE).all_tags())
    ]
    assert release_tags == ["r28_0_1", "r28_0_0", "r27_0_0"]

    weekly_tags = [
        x.tag for x in list(filtered.by_type(RSPImageType.WEEKLY).all_tags())
    ]
    assert len(weekly_tags) >= 1
    assert len(weekly_tags) <= 3
    assert to_weekly_tag(last_week) in weekly_tags

    daily_tags = [
        x.tag for x in list(filtered.by_type(RSPImageType.DAILY).all_tags())
    ]
    assert len(daily_tags) >= 1
    assert len(daily_tags) <= 3
    assert to_daily_tag(yesterday) in daily_tags

    rc_tags = [
        x.tag
        for x in list(filtered.by_type(RSPImageType.CANDIDATE).all_tags())
    ]
    assert rc_tags == ["r28_0_0_rc1"]

    exp_tags = [
        x.tag
        for x in list(filtered.by_type(RSPImageType.EXPERIMENTAL).all_tags())
    ]
    assert len(exp_tags) >= 1
    assert len(exp_tags) <= 3
    assert f"exp_{to_weekly_tag(yesterday)}" in exp_tags

    unknown_tags = [
        x.tag for x in list(filtered.by_type(RSPImageType.UNKNOWN).all_tags())
    ]
    assert unknown_tags == []
