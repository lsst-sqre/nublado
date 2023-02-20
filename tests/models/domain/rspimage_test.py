"""Tests of abstract data types for Docker image analysis."""

from __future__ import annotations

import os
from dataclasses import asdict
from random import SystemRandom

import pytest
from semver import VersionInfo

from jupyterlabcontroller.models.domain.rspimage import (
    RSPImage,
    RSPImageCollection,
)
from jupyterlabcontroller.models.domain.rsptag import RSPImageTag, RSPImageType


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
        "cycle": None,
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
    recommended = RSPImage.from_tag(
        registry="lighthouse.ceres",
        repository="library/sketchbook",
        tag=RSPImageTag.from_str("recommended"),
        digest="sha256:1234",
    )
    assert recommended.image_type == RSPImageType.UNKNOWN
    assert recommended.display_name == "recommended"
    assert recommended.alias_target is None
    assert recommended.cycle is None
    assert recommended.is_possible_alias

    recommended.resolve_alias(image)
    assert recommended.image_type == RSPImageType.ALIAS
    assert recommended.alias_target == "d_2077_10_23_c0045.003"
    assert image.aliases == {"recommended"}
    assert recommended.display_name == f"Recommended ({image.display_name})"
    assert recommended.cycle == 45
    assert recommended.is_possible_alias

    # Can do the same thing with a tag that's already an alias.
    latest_daily = RSPImage.from_tag(
        registry="lighthouse.ceres",
        repository="library/sketchbook",
        tag=RSPImageTag.alias("latest_daily"),
        digest="sha256:1234",
    )
    assert latest_daily.image_type == RSPImageType.ALIAS
    assert latest_daily.display_name == "Latest Daily"

    latest_daily.resolve_alias(image)
    assert latest_daily.image_type == RSPImageType.ALIAS
    assert latest_daily.alias_target == "d_2077_10_23_c0045.003"
    assert image.aliases == {"recommended", "latest_daily"}
    assert latest_daily.display_name == f"Latest Daily ({image.display_name})"

    # Can't resolve some other image type.
    with pytest.raises(ValueError):
        image.resolve_alias(latest_daily)


def make_test_image(tag: str) -> RSPImage:
    """Create a test image from a tag with a random digest."""
    return RSPImage.from_tag(
        registry="lighthouse.ceres",
        repository="library/sketchbook",
        tag=RSPImageTag.from_str(tag),
        digest="sha256:" + os.urandom(32).hex(),
    )


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
    # should get promoted to an alias.
    latest_weekly = RSPImage.from_tag(
        registry="lighthouse.ceres",
        repository="library/sketchbook",
        tag=RSPImageTag.from_str("latest_weekly"),
        digest=images[0].digest,
    )
    assert latest_weekly.image_type == RSPImageType.UNKNOWN
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
    assert all_images == ["recommended", "latest_weekly"] + tags
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
