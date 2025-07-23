"""Tests of abstract data types for Docker image analysis."""

from __future__ import annotations

import os
from dataclasses import asdict
from datetime import UTC, datetime
from random import SystemRandom
from typing import cast

import pytest
from semver.version import VersionInfo

from controller.models.domain.rspimage import RSPImage, RSPImageCollection
from controller.models.domain.rsptag import RSPImageTag, RSPImageType


def make_test_image(tag: str) -> RSPImage:
    """Create a test image from a tag with a random digest."""
    return RSPImage.from_tag(
        registry="lighthouse.ceres",
        repository="library/sketchbook",
        tag=RSPImageTag.from_str(tag),
        digest="sha256:" + os.urandom(32).hex(),
    )


def test_image() -> None:
    """Test RSPImage class."""
    image = RSPImage.from_tag(
        registry="lighthouse.ceres",
        repository="library/sketchbook",
        tag=RSPImageTag.from_str("d_2077_10_23"),
        digest="sha256:1234",
    )
    assert asdict(image) == {
        "tag": "d_2077_10_23",
        "image_type": RSPImageType.DAILY,
        "display_name": "Daily 2077_10_23",
        "version": VersionInfo(2077, 10, 23),
        "rsp_version": None,
        "cycle": None,
        "date": datetime(2077, 10, 23, tzinfo=UTC),
        "registry": "lighthouse.ceres",
        "repository": "library/sketchbook",
        "digest": "sha256:1234",
        "size": None,
        "aliases": set(),
        "alias_target": None,
        "nodes": set(),
    }
    assert image.reference == (
        "lighthouse.ceres/library/sketchbook:d_2077_10_23"
    )
    assert image.reference_with_digest == (
        "lighthouse.ceres/library/sketchbook:d_2077_10_23@sha256:1234"
    )
    assert not image.is_possible_alias


def test_resolve_alias() -> None:
    """Test enhancing an RSPImage alias."""
    image = RSPImage.from_tag(
        registry="lighthouse.ceres",
        repository="library/sketchbook",
        tag=RSPImageTag.from_str("d_2077_10_23_c0045.003"),
        digest="sha256:1234",
    )
    assert image.cycle == 45
    assert image.date == datetime(2077, 10, 23, tzinfo=UTC)
    recommended = RSPImage.from_tag(
        registry="lighthouse.ceres",
        repository="library/sketchbook",
        tag=RSPImageTag.from_str("recommended"),
        digest="sha256:1234",
    )

    # resolve_alias(), called below, may change image_type, but mypy doesn't
    # have enough information to know that and preserves type narrowing. This
    # is therefore written a little oddly to prevent mypy from doing type
    # narrowing.
    expected = RSPImageType.UNKNOWN
    assert recommended.image_type == expected
    assert recommended.display_name == "recommended"
    assert recommended.alias_target is None
    assert recommended.cycle is None
    assert recommended.date is None
    assert recommended.is_possible_alias

    recommended.resolve_alias(image)
    assert recommended.image_type == RSPImageType.ALIAS
    assert recommended.alias_target == "d_2077_10_23_c0045.003"
    assert image.aliases == {"recommended"}
    assert recommended.display_name == (
        "Recommended (Daily 2077_10_23, SAL Cycle 0045, Build 003)"
    )
    assert recommended.cycle == 45
    assert recommended.date == datetime(2077, 10, 23, tzinfo=UTC)
    assert recommended.is_possible_alias

    # Can do the same thing with a tag that's already an alias.
    latest_daily = RSPImage.from_tag(
        registry="lighthouse.ceres",
        repository="library/sketchbook",
        tag=RSPImageTag.alias("latest_daily_c0045"),
        digest="sha256:1234",
    )
    assert latest_daily.image_type == RSPImageType.ALIAS
    assert latest_daily.display_name == "Latest Daily (SAL Cycle 0045)"
    assert latest_daily.date is None

    latest_daily.resolve_alias(image)
    assert latest_daily.image_type == RSPImageType.ALIAS
    assert latest_daily.alias_target == "d_2077_10_23_c0045.003"
    assert latest_daily.aliases == {"recommended"}
    assert image.aliases == {"recommended", "latest_daily_c0045"}
    assert latest_daily.display_name == (
        "Latest Daily (Daily 2077_10_23, SAL Cycle 0045, Build 003)"
    )
    assert latest_daily.date == datetime(2077, 10, 23, tzinfo=UTC)

    # Can't resolve some other image type.
    with pytest.raises(ValueError, match=r"Can only resolve.*"):
        image.resolve_alias(latest_daily)


def test_collection() -> None:
    """Test RSPImageCollection."""
    tags = ["w_2077_46", "w_2077_45", "w_2077_44", "w_2077_43", "d_2077_10_21"]
    images = [make_test_image(t) for t in tags]

    # Add an alias image with the same digest as the first image.
    recommended = RSPImage.from_tag(
        registry="lighthouse.ceres",
        repository="library/sketchbook",
        tag=RSPImageTag.alias("recommended"),
        digest=images[0].digest,
    )
    images.append(recommended)

    # Add an unknown image with the same digest as the first image. This
    # should start as an unknown tag but get promoted to an alias once
    # ingested into a collection.
    latest_weekly = RSPImage.from_tag(
        registry="lighthouse.ceres",
        repository="library/sketchbook",
        tag=RSPImageTag.from_str("latest_weekly"),
        digest=images[0].digest,
    )

    # resolve_alias(), called below, may change image_type, but mypy doesn't
    # have enough information to know that and preserves type narrowing. This
    # is therefore written a little oddly to prevent mypy from doing type
    # narrowing.
    expected = RSPImageType.UNKNOWN
    assert latest_weekly.image_type == expected
    images.append(latest_weekly)

    # Ingest into a collection.
    shuffled_images = list(images)
    SystemRandom().shuffle(shuffled_images)
    assert images[0].aliases == set()
    collection = RSPImageCollection(shuffled_images)
    assert latest_weekly.image_type == RSPImageType.ALIAS
    assert latest_weekly.alias_target == "w_2077_46"
    assert recommended.alias_target == "w_2077_46"
    assert images[0].aliases == {"recommended", "latest_weekly"}

    # Test asking for tags by name or the latest of a type.
    assert collection.image_for_tag_name(images[0].tag) == images[0]
    assert collection.image_for_tag_name("recommended") == recommended
    assert collection.latest(RSPImageType.WEEKLY) == images[0]
    assert collection.latest(RSPImageType.DAILY) == images[4]
    assert collection.latest(RSPImageType.RELEASE) is None

    # recommended and w_2077_46 have the same digest, but we should always
    # return the latter rather than the alias when retrieving by digest.
    assert collection.image_for_digest(images[0].digest) == images[0]

    # Test all_images, its sorting, and its filtering options.
    all_images = [i.tag for i in collection.all_images()]
    assert all_images == ["recommended", "latest_weekly", *tags]
    without_aliases = collection.all_images(hide_resolved_aliases=True)
    assert [i.tag for i in without_aliases] == tags
    assert [i.tag for i in collection.all_images(hide_aliased=True)] == [
        "recommended",
        "latest_weekly",
        "w_2077_45",
        "w_2077_44",
        "w_2077_43",
        "d_2077_10_21",
    ]

    # Test subsetting.
    subset = collection.subset(releases=1, weeklies=3, dailies=1)
    assert [t.tag for t in subset.all_images()] == [
        "w_2077_46",
        "w_2077_45",
        "w_2077_44",
        "d_2077_10_21",
    ]
    subset = collection.subset(
        releases=1, weeklies=3, dailies=1, include={"recommended"}
    )
    assert [t.tag for t in subset.all_images()] == [
        "recommended",
        "w_2077_46",
        "w_2077_45",
        "w_2077_44",
        "d_2077_10_21",
    ]
    subset = subset.subset(weeklies=1)
    assert [t.tag for t in subset.all_images()] == ["w_2077_46"]

    # Test subtraction. Note that this only returns one image per digest and
    # prefers the non-alias images.
    other = RSPImageCollection(images[0:2])
    remainder = collection.subtract(other)
    assert [i.tag for i in remainder.all_images()] == [
        "w_2077_44",
        "w_2077_43",
        "d_2077_10_21",
    ]

    # Test adding images. There is a special case here where we add an alias
    # image and then later add its target, and want to switch which of them is
    # the one retrieved by digest. We're setting up a test for that.
    first = RSPImage.from_tag(
        registry="lighthouse.ceres",
        repository="library/sketchbook",
        tag=RSPImageTag.from_str("recommended"),
        digest="sha256:" + os.urandom(32).hex(),
    )
    collection = RSPImageCollection([first])
    assert collection.image_for_digest(first.digest) == first
    assert list(collection.all_images()) == [first]
    assert list(collection.all_images(hide_resolved_aliases=True)) == [first]

    # Now add another alias. This should not replace the first as the image to
    # retrieve by digest, nor should it be enhanced.
    second = RSPImage.from_tag(
        registry="lighthouse.ceres",
        repository="library/sketchbook",
        tag=RSPImageTag.alias("latest_weekly"),
        digest=first.digest,
    )
    assert second.alias_target is None
    collection.add(second)
    assert second.alias_target is None
    assert collection.image_for_digest(first.digest) == first
    assert list(collection.all_images()) == [second, first]
    contents = list(collection.all_images(hide_resolved_aliases=True))
    assert contents == [second, first]

    # Finally, add the non-alias image with the same hash as both of these.
    third = RSPImage.from_tag(
        registry="lighthouse.ceres",
        repository="library/sketchbook",
        tag=RSPImageTag.from_str("w_2077_44"),
        digest=first.digest,
    )
    collection.add(third)
    assert first.alias_target == third.tag
    assert second.alias_target == third.tag
    assert third.aliases == {first.tag, second.tag}
    assert collection.image_for_digest(first.digest) == third
    assert list(collection.all_images(hide_resolved_aliases=True)) == [third]

    # Note that first has been promoted to an alias and therefore changed its
    # sort location.
    assert list(collection.all_images()) == [first, second, third]


def test_alias_tracking() -> None:
    """Test alias tracking inside an image collection."""
    weekly = make_test_image("w_2077_46")
    recommended = RSPImage.from_tag(
        registry="lighthouse.ceres",
        repository="library/sketchbook",
        tag=RSPImageTag.alias("recommended"),
        digest=weekly.digest,
    )
    latest_weekly = RSPImage.from_tag(
        registry="lighthouse.ceres",
        repository="library/sketchbook",
        tag=RSPImageTag.from_str("latest_weekly"),
        digest=weekly.digest,
    )

    # Make another non-alias image that has the same digest as w_2077_46.
    old_weekly = make_test_image("w_2077_45")
    old_weekly.digest = weekly.digest

    # If we put these all into the collection at the same time, they should
    # all alias each other, with the alias tags pointing to the non-alias tags
    # using the alias_target attribute and the non-alias tags marked as
    # aliased.
    images = [weekly, old_weekly, recommended, latest_weekly]
    collection = RSPImageCollection(images)
    assert weekly.aliases == {"recommended", "latest_weekly", "w_2077_45"}
    assert not weekly.alias_target
    assert old_weekly.aliases == {"recommended", "latest_weekly", "w_2077_46"}
    assert not old_weekly.alias_target
    assert recommended.aliases == {"latest_weekly", "w_2077_45"}
    assert recommended.alias_target == "w_2077_46"
    assert latest_weekly.aliases == {"recommended", "w_2077_45"}
    assert latest_weekly.alias_target == "w_2077_46"
    assert [i.tag for i in collection.all_images(hide_aliased=True)] == [
        "recommended",
        "latest_weekly",
        "w_2077_45",
    ]

    # If we add them one at a time, we should reach the same end state.
    # Recreate the images to ensure that we don't have any left-over alias
    # information.
    weekly = make_test_image("w_2077_46")
    recommended = RSPImage.from_tag(
        registry="lighthouse.ceres",
        repository="library/sketchbook",
        tag=RSPImageTag.alias("recommended"),
        digest=weekly.digest,
    )
    latest_weekly = RSPImage.from_tag(
        registry="lighthouse.ceres",
        repository="library/sketchbook",
        tag=RSPImageTag.from_str("latest_weekly"),
        digest=weekly.digest,
    )
    old_weekly = make_test_image("w_2077_45")
    old_weekly.digest = weekly.digest
    collection = RSPImageCollection([])
    for image in (old_weekly, weekly, recommended, latest_weekly):
        collection.add(image)
    assert weekly.aliases == {"recommended", "latest_weekly", "w_2077_45"}
    assert not weekly.alias_target
    assert old_weekly.aliases == {"recommended", "latest_weekly", "w_2077_46"}
    assert not old_weekly.alias_target
    assert recommended.aliases == {"latest_weekly", "w_2077_45"}
    assert recommended.alias_target == "w_2077_46"
    assert latest_weekly.aliases == {"recommended", "w_2077_45"}
    assert latest_weekly.alias_target == "w_2077_46"
    assert [i.tag for i in collection.all_images(hide_aliased=True)] == [
        "recommended",
        "latest_weekly",
        "w_2077_45",
    ]

    # If we have two potential alias images with the same digest, and we add
    # them but not the underlying "real" image, they should alias each other.
    weekly = make_test_image("w_2077_46")
    recommended = RSPImage.from_tag(
        registry="lighthouse.ceres",
        repository="library/sketchbook",
        tag=RSPImageTag.alias("recommended"),
        digest=weekly.digest,
    )
    latest_weekly = RSPImage.from_tag(
        registry="lighthouse.ceres",
        repository="library/sketchbook",
        tag=RSPImageTag.from_str("latest_weekly"),
        digest=weekly.digest,
    )
    collection = RSPImageCollection([recommended, latest_weekly])
    assert recommended.aliases == {"latest_weekly"}
    assert not recommended.alias_target
    assert latest_weekly.aliases == {"recommended"}
    assert not latest_weekly.alias_target

    # Then, when the actual image is added, they should both resolve to it.
    # mypy doesn't understand collection side effects, so needs an explicit
    # cast in a few places.
    collection.add(weekly)
    assert weekly.aliases == {"recommended", "latest_weekly"}
    assert not weekly.alias_target
    assert recommended.aliases == {"latest_weekly"}
    assert cast("str", recommended.alias_target) == "w_2077_46"
    assert latest_weekly.aliases == {"recommended"}
    assert cast("str", latest_weekly.alias_target) == "w_2077_46"
    assert [i.tag for i in collection.all_images(hide_aliased=True)] == [
        "recommended",
        "latest_weekly",
    ]

    # If we add another image with the same digest, it should take over as the
    # primary alias target.
    assert recommended.display_name == "Recommended (Weekly 2077_46)"
    new_weekly = make_test_image("w_2077_47")
    new_weekly.digest = weekly.digest
    collection.add(new_weekly)
    assert weekly.aliases == {"recommended", "latest_weekly", "w_2077_47"}
    assert not weekly.alias_target
    assert new_weekly.aliases == {"recommended", "latest_weekly", "w_2077_46"}
    assert not new_weekly.alias_target
    assert recommended.aliases == {"latest_weekly", "w_2077_46"}
    assert cast("str", recommended.alias_target) == "w_2077_47"
    assert recommended.display_name == "Recommended (Weekly 2077_47)"
    assert latest_weekly.aliases == {"recommended", "w_2077_46"}
    assert cast("str", latest_weekly.alias_target) == "w_2077_47"
    assert [i.tag for i in collection.all_images(hide_aliased=True)] == [
        "recommended",
        "latest_weekly",
        "w_2077_46",
    ]

    # If images alias things that aren't in the collection, we should just
    # ignore that rather than producing errors.
    recommended = RSPImage.from_tag(
        registry="lighthouse.ceres",
        repository="library/sketchbook",
        tag=RSPImageTag.alias("recommended"),
        digest=weekly.digest,
    )
    recommended.aliases.add("latest_daily")
    latest_weekly = RSPImage.from_tag(
        registry="lighthouse.ceres",
        repository="library/sketchbook",
        tag=RSPImageTag.alias("latest_weekly"),
        digest=weekly.digest,
    )
    latest_weekly.aliases.add("latest_daily")
    collection = RSPImageCollection([recommended])
    collection.add(latest_weekly)
    assert recommended.aliases == {"latest_daily", "latest_weekly"}
    assert latest_weekly.aliases == {"latest_daily", "recommended"}


def test_node_tracking() -> None:
    """Test node presence tracking inside a collection."""
    weekly = make_test_image("w_2077_46")
    weekly.aliases.add("nonexistent_tag")
    recommended = RSPImage.from_tag(
        registry="lighthouse.ceres",
        repository="library/sketchbook",
        tag=RSPImageTag.alias("recommended"),
        digest=weekly.digest,
    )
    collection = RSPImageCollection((recommended, weekly))
    assert weekly.nodes == set()
    assert weekly.size is None
    assert recommended.alias_target == "w_2077_46"
    assert recommended.nodes == set()
    assert recommended.size is None

    # Marking an image whose digest we've never seen should quietly do
    # nothing.
    collection.mark_image_seen_on_node("bogusdigest", "node1", 123456)

    # Marking a known image as seen on a node should update everything.
    collection.mark_image_seen_on_node(weekly.digest, "node1")
    assert weekly.nodes == {"node1"}
    assert weekly.size is None
    assert recommended.nodes == {"node1"}
    assert recommended.size is None

    # If we include size information, the size should get updated everywhere.
    collection.mark_image_seen_on_node(weekly.digest, "node2", 123456)
    assert weekly.nodes == {"node1", "node2"}
    assert weekly.size == 123456
    assert recommended.nodes == {"node1", "node2"}
    assert recommended.size == 123456


def test_hide_aliased() -> None:
    """Don't hide an aliased image if the alias is not in the collection.

    We don't want to repeat images in the menu, but when Google Artifact
    Repository is in use, images on the menu may be aliased by alias tags that
    aren't in the menu. When hiding aliased images, we therefore want to only
    hide the image if one of its aliases is in the same collection.
    """
    weekly = make_test_image("w_2077_46")
    weekly.aliases.add("nonexistent_tag")
    collection = RSPImageCollection([weekly])
    images = collection.all_images(hide_aliased=True)
    assert [i.tag for i in images] == ["w_2077_46"]


def test_hide_resolved() -> None:
    """Don't hide a resolved alias if its target isn't in the collection."""
    weekly = make_test_image("w_2077_46")
    recommended = RSPImage.from_tag(
        registry="lighthouse.ceres",
        repository="library/sketchbook",
        tag=RSPImageTag.alias("recommended"),
        digest=weekly.digest,
    )
    collection = RSPImageCollection((recommended, weekly))

    # This will have resolved the alias. Now recreate the collection with just
    # the alias tag. Even though it's still marked as resolved, it should not
    # be hidden.
    collection = RSPImageCollection([recommended])
    assert recommended.alias_target == "w_2077_46"
    images = collection.all_images(hide_resolved_aliases=True)
    assert [i.tag for i in images] == ["recommended"]
