"""Tests of Docker image tag parsing and analysis."""

from __future__ import annotations

from dataclasses import asdict
from random import SystemRandom

import pytest
from semver.version import VersionInfo

from jupyterlabcontroller.models.domain.rsptag import (
    RSPImageTag,
    RSPImageTagCollection,
    RSPImageType,
)


def test_tag_ordering() -> None:
    """Test comparisons of RSPImageTag objects."""
    one = RSPImageTag.from_str("r21_0_1")
    two = RSPImageTag.from_str("r21_0_2")
    assert one == one
    assert one <= one
    assert one >= one
    assert one != two
    assert one < two
    assert one <= two
    assert two >= one

    three = RSPImageTag.from_str("d_2023_02_09")
    assert three == three
    assert one != three
    with pytest.raises(TypeError):
        one < three
    with pytest.raises(TypeError):
        one > three

    four = RSPImageTag.from_str("d_2023_02_10_c0030.004")
    assert three != four
    assert three < four

    five = RSPImageTag.from_str("d_2023_02_10_c0031.004")
    assert four != five
    assert four < five

    six = RSPImageTag.from_str("d_2023_02_10_c0031.005")
    assert five != six
    assert five < six

    exp_one = RSPImageTag.from_str("exp_20230209")
    exp_two = RSPImageTag.from_str("exp_random")
    assert exp_one == exp_one
    assert exp_one != exp_two
    assert exp_one < exp_two


def test_alias() -> None:
    """Test alias constructor for an RSPImageTag."""
    tag = RSPImageTag.alias("recommended")
    assert asdict(tag) == {
        "tag": "recommended",
        "image_type": RSPImageType.ALIAS,
        "version": None,
        "cycle": None,
        "display_name": "Recommended",
    }

    # If there is a cycle, we should extract it.
    tag = RSPImageTag.alias("latest_weekly_c0046")
    assert asdict(tag) == {
        "tag": "latest_weekly_c0046",
        "image_type": RSPImageType.ALIAS,
        "version": None,
        "cycle": 46,
        "display_name": "Latest Weekly (SAL Cycle 0046)",
    }


def test_collection() -> None:
    """Test behavior of an RSPImageTagCollection object."""
    # This tag list must be kept in expected sorted order.
    tags = [
        "r21_0_1",
        "r20_0_1_c0027.001",
        "w_2077_46",
        "w_2077_45",
        "w_2077_44",
        "w_2077_43",
        "w_2077_42",
        "w_2077_40_c0027.001",
        "w_2077_40_c0026.001",
        "d_2077_10_21",
        "d_2077_10_20",
        "r22_0_0_rc1",
        "exp_w_2021_22",
        "recommended_c0027",
        "recommended",
    ]
    shuffled_tags = list(tags)
    SystemRandom().shuffle(shuffled_tags)

    collection = RSPImageTagCollection.from_tag_names(shuffled_tags, set())
    assert [t.tag for t in collection.all_tags()] == tags
    tag = collection.tag_for_tag_name("w_2077_46")
    assert tag
    assert tag.tag == "w_2077_46"
    assert collection.tag_for_tag_name("w_2080_01") is None

    # Filter by cycle.
    collection = RSPImageTagCollection.from_tag_names(
        shuffled_tags, set(), cycle=27
    )
    assert [t.tag for t in collection.all_tags()] == [
        "r20_0_1_c0027.001",
        "w_2077_40_c0027.001",
        "recommended_c0027",
    ]

    # Alias tag identification.
    unknown = [
        t.tag
        for t in collection.all_tags()
        if t.image_type == RSPImageType.UNKNOWN
    ]
    assert unknown == ["recommended_c0027"]
    recommended = {"recommended", "recommended_c0027"}
    collection = RSPImageTagCollection.from_tag_names(
        shuffled_tags, recommended
    )
    aliases = {
        t.tag
        for t in collection.all_tags()
        if t.image_type == RSPImageType.ALIAS
    }
    assert aliases == recommended
    assert next(collection.all_tags()).tag == "recommended_c0027"

    # Subsetting.
    subset = collection.subset(releases=1, weeklies=3, dailies=1)
    assert [t.tag for t in subset.all_tags()] == [
        "r21_0_1",
        "w_2077_46",
        "w_2077_45",
        "w_2077_44",
        "d_2077_10_21",
    ]
    subset = collection.subset(
        releases=1, weeklies=3, dailies=1, include={"recommended"}
    )
    assert [t.tag for t in subset.all_tags()] == [
        "recommended",
        "r21_0_1",
        "w_2077_46",
        "w_2077_45",
        "w_2077_44",
        "d_2077_10_21",
    ]
    subset = subset.subset(dailies=1)
    assert [t.tag for t in subset.all_tags()] == ["d_2077_10_21"]


def test_from_str() -> None:
    """Parse tags into RSPImageTag objects."""
    test_cases = {
        "r21_0_1": {
            "tag": "r21_0_1",
            "image_type": RSPImageType.RELEASE,
            "display_name": "Release r21.0.1",
            "version": VersionInfo(21, 0, 1),
            "cycle": None,
        },
        "r22_0_0_rc1": {
            "tag": "r22_0_0_rc1",
            "image_type": RSPImageType.CANDIDATE,
            "display_name": "Release Candidate r22.0.0-rc1",
            "version": VersionInfo(22, 0, 0, "rc1"),
            "cycle": None,
        },
        "w_2021_22": {
            "tag": "w_2021_22",
            "image_type": RSPImageType.WEEKLY,
            "display_name": "Weekly 2021_22",
            "version": VersionInfo(2021, 22, 0),
            "cycle": None,
        },
        "d_2021_05_27": {
            "tag": "d_2021_05_27",
            "image_type": RSPImageType.DAILY,
            "display_name": "Daily 2021_05_27",
            "version": VersionInfo(2021, 5, 27),
            "cycle": None,
        },
        "r21_0_1_c0020.001": {
            "tag": "r21_0_1_c0020.001",
            "image_type": RSPImageType.RELEASE,
            "display_name": "Release r21.0.1 (SAL Cycle 0020, Build 001)",
            "version": VersionInfo(21, 0, 1, None, "c0020.001"),
            "cycle": 20,
        },
        "r22_0_0_rc1_c0020.001": {
            "tag": "r22_0_0_rc1_c0020.001",
            "image_type": RSPImageType.CANDIDATE,
            "display_name": (
                "Release Candidate r22.0.0-rc1 (SAL Cycle 0020, Build 001)"
            ),
            "version": VersionInfo(22, 0, 0, "rc1", "c0020.001"),
            "cycle": 20,
        },
        "w_2021_22_c0020.001": {
            "tag": "w_2021_22_c0020.001",
            "image_type": RSPImageType.WEEKLY,
            "display_name": "Weekly 2021_22 (SAL Cycle 0020, Build 001)",
            "version": VersionInfo(2021, 22, 0, None, "c0020.001"),
            "cycle": 20,
        },
        "d_2021_05_27_c0020.001": {
            "tag": "d_2021_05_27_c0020.001",
            "image_type": RSPImageType.DAILY,
            "display_name": "Daily 2021_05_27 (SAL Cycle 0020, Build 001)",
            "version": VersionInfo(2021, 5, 27, None, "c0020.001"),
            "cycle": 20,
        },
        "r21_0_1_20210527": {
            "tag": "r21_0_1_20210527",
            "image_type": RSPImageType.RELEASE,
            "display_name": "Release r21.0.1 [20210527]",
            "version": VersionInfo(21, 0, 1, None, "20210527"),
            "cycle": None,
        },
        "r22_0_0_rc1_20210527": {
            "tag": "r22_0_0_rc1_20210527",
            "image_type": RSPImageType.CANDIDATE,
            "display_name": "Release Candidate r22.0.0-rc1 [20210527]",
            "version": VersionInfo(22, 0, 0, "rc1", "20210527"),
            "cycle": None,
        },
        "w_2021_22_20210527": {
            "tag": "w_2021_22_20210527",
            "image_type": RSPImageType.WEEKLY,
            "display_name": "Weekly 2021_22 [20210527]",
            "version": VersionInfo(2021, 22, 0, None, "20210527"),
            "cycle": None,
        },
        "d_2021_05_27_20210527": {
            "tag": "d_2021_05_27_20210527",
            "image_type": RSPImageType.DAILY,
            "display_name": "Daily 2021_05_27 [20210527]",
            "version": VersionInfo(2021, 5, 27, None, "20210527"),
            "cycle": None,
        },
        "r21_0_1_c0020.001_20210527": {
            "tag": "r21_0_1_c0020.001_20210527",
            "image_type": RSPImageType.RELEASE,
            "display_name": (
                "Release r21.0.1 (SAL Cycle 0020, Build 001) [20210527]"
            ),
            "version": VersionInfo(21, 0, 1, None, "c0020.001.20210527"),
            "cycle": 20,
        },
        "r22_0_0_rc1_c0020.001_20210527": {
            "tag": "r22_0_0_rc1_c0020.001_20210527",
            "image_type": RSPImageType.CANDIDATE,
            "display_name": (
                "Release Candidate r22.0.0-rc1 (SAL Cycle 0020, Build 001)"
                " [20210527]"
            ),
            "version": VersionInfo(22, 0, 0, "rc1", "c0020.001.20210527"),
            "cycle": 20,
        },
        "w_2021_22_c0020.001_20210527": {
            "tag": "w_2021_22_c0020.001_20210527",
            "image_type": RSPImageType.WEEKLY,
            "display_name": (
                "Weekly 2021_22 (SAL Cycle 0020, Build 001) [20210527]"
            ),
            "version": VersionInfo(2021, 22, 0, None, "c0020.001.20210527"),
            "cycle": 20,
        },
        "d_2021_05_27_c0020.001_20210527": {
            "tag": "d_2021_05_27_c0020.001_20210527",
            "image_type": RSPImageType.DAILY,
            "display_name": (
                "Daily 2021_05_27 (SAL Cycle 0020, Build 001) [20210527]"
            ),
            "version": VersionInfo(2021, 5, 27, None, "c0020.001.20210527"),
            "cycle": 20,
        },
        "recommended": {
            "tag": "recommended",
            "image_type": RSPImageType.UNKNOWN,
            "display_name": "recommended",
            "version": None,
            "cycle": None,
        },
        "exp_random": {
            "tag": "exp_random",
            "image_type": RSPImageType.EXPERIMENTAL,
            "display_name": "Experimental random",
            "version": None,
            "cycle": None,
        },
        "exp_w_2021_22": {
            "tag": "exp_w_2021_22",
            "image_type": RSPImageType.EXPERIMENTAL,
            "display_name": "Experimental Weekly 2021_22",
            "version": None,
            "cycle": None,
        },
        "exp_w_2021_22_c0020.001": {
            "tag": "exp_w_2021_22_c0020.001",
            "image_type": RSPImageType.EXPERIMENTAL,
            "display_name": (
                "Experimental Weekly 2021_22 (SAL Cycle 0020, Build 001)"
            ),
            "version": None,
            "cycle": 20,
        },
        "exp_w_2021_22_c0020.001_foo": {
            "tag": "exp_w_2021_22_c0020.001_foo",
            "image_type": RSPImageType.EXPERIMENTAL,
            "display_name": (
                "Experimental Weekly 2021_22 (SAL Cycle 0020, Build 001) [foo]"
            ),
            "version": None,
            "cycle": 20,
        },
        "recommended_c0027": {
            "tag": "recommended_c0027",
            "image_type": RSPImageType.UNKNOWN,
            "display_name": "recommended (SAL Cycle 0027)",
            "version": None,
            "cycle": 27,
        },
        "not_a_normal_format": {
            "tag": "not_a_normal_format",
            "image_type": RSPImageType.UNKNOWN,
            "display_name": "not_a_normal_format",
            "version": None,
            "cycle": None,
        },
        "MiXeD_CaSe_TaG": {
            "tag": "MiXeD_CaSe_TaG",
            "image_type": RSPImageType.UNKNOWN,
            "display_name": "MiXeD_CaSe_TaG",
            "version": None,
            "cycle": None,
        },
        "": {
            "tag": "latest",
            "image_type": RSPImageType.UNKNOWN,
            "display_name": "latest",
            "version": None,
            "cycle": None,
        },
    }

    # RSPImageTag equality is based only on the type and version or tag, so in
    # order to ensure we got all of the fields correct, we have to compare
    # them in dictionary form.
    for tag, expected in test_cases.items():
        assert asdict(RSPImageTag.from_str(tag)) == expected
