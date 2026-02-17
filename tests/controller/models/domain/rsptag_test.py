"""Tests of Docker image tag parsing and analysis."""

from __future__ import annotations

from dataclasses import asdict
from random import SystemRandom

import pytest

from nublado.controller.models.domain.rsptag import (
    RSPImageTag,
    RSPImageTagCollection,
    RSPImageType,
)

from ....support.data import NubladoData


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
        assert one < three
    with pytest.raises(TypeError):
        assert one > three

    four = RSPImageTag.from_str("d_2023_02_10_c0030.004")
    assert three != four
    assert three < four

    five = RSPImageTag.from_str("d_2023_02_10_c0031.004")
    assert four != five
    assert four < five

    six = RSPImageTag.from_str("d_2023_02_10_c0031.005")
    assert five != six
    assert five < six

    seven = RSPImageTag.from_str("r21_0_1_rsp29")
    assert one != seven
    assert one < seven

    eight = RSPImageTag.from_str("r21_0_1_rsp103")
    assert seven != eight
    assert seven < eight

    nine = RSPImageTag.from_str("r21_0_1_rsp103_extra")
    assert eight != nine
    assert eight < nine

    ten = RSPImageTag.from_str("r21_0_1_rsp103_foo")
    assert nine != ten
    assert nine < ten

    assert ten == RSPImageTag.from_str("r21_0_1_rsp103_foo")

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
        "cycle_build": None,
        "rsp_build": None,
        "display_name": "Recommended",
        "date": None,
    }

    # If there is a cycle, we should extract it.
    tag = RSPImageTag.alias("latest_weekly_c0046")
    assert asdict(tag) == {
        "tag": "latest_weekly_c0046",
        "image_type": RSPImageType.ALIAS,
        "version": None,
        "cycle": 46,
        "cycle_build": None,
        "rsp_build": None,
        "display_name": "Latest Weekly (SAL Cycle 0046)",
        "date": None,
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


def test_from_str(data: NubladoData) -> None:
    """Parse tags into RSPImageTag objects.

    To add more tests, add a new file in tests/data/controller/rsptag whose
    name is the string form of the tag plus .json and whose contents is the
    JSON representation of the dictionary format of the parsed tag.
    Alternately, start with a file containing ``{}`` and then run the test
    with ``--update-test-data``.

    Variations for optional data are tested in ``test_from_str_variant``.
    """
    for output in data.path("controller/rspimagetag").iterdir():
        if output.suffix != ".json":
            continue
        tag = output.stem
        result = RSPImageTag.from_str(tag).to_dict()
        data.assert_json_matches(result, f"controller/rspimagetag/{tag}")

    # Test a couple more edge cases where the input tag string may pose
    # problems for the file system and therefore cannot be used as a file
    # name.
    assert RSPImageTag.from_str("MiXeD_CaSe_TaG").to_dict() == {
        "tag": "MiXeD_CaSe_TaG",
        "image_type": "Unknown",
        "version": None,
        "cycle": None,
        "cycle_build": None,
        "rsp_build": None,
        "display_name": "MiXeD_CaSe_TaG",
        "date": None,
    }
    assert RSPImageTag.from_str("").to_dict() == {
        "tag": "latest",
        "image_type": "Unknown",
        "version": None,
        "cycle": None,
        "cycle_build": None,
        "rsp_build": None,
        "display_name": "latest",
        "date": None,
    }


@pytest.mark.parametrize(
    "tag", ["d_2021_05_27", "w_2021_22", "r22_0_0_rc1", "r21_0_1"]
)
@pytest.mark.parametrize("experimental", [True, False])
@pytest.mark.parametrize("rsp_build", [None, 19])
@pytest.mark.parametrize("cycle", [None, ("0020", "001")])
@pytest.mark.parametrize("extra", [None, "20210527", "random"])
def test_from_str_varient(
    data: NubladoData,
    *,
    tag: str,
    experimental: bool,
    rsp_build: int | None,
    cycle: tuple[str, str] | None,
    extra: str | None,
) -> None:
    """Test all the variations of each tag.

    Starting from each of the four types of base tags, check all the
    variations of optional data that can be added to any tag format.
    """
    expected = data.read_json(f"controller/rspimagetag/{tag}")

    # Modify the tag and expected output based on the parameterized arguments.
    if experimental:
        tag = "exp_" + tag
        expected["image_type"] = "Experimental"
        expected["display_name"] = "Experimental " + expected["display_name"]
    if rsp_build:
        tag += f"_rsp{rsp_build}"
        expected["display_name"] += f" (RSP Build {rsp_build})"
        expected["rsp_build"] = rsp_build
    if cycle:
        cycle_str = f"c{cycle[0]}.{cycle[1]}"
        tag += f"_{cycle_str}"
        expected["cycle"] = int(cycle[0])
        expected["cycle_build"] = int(cycle[1])
        extra_display = f" (SAL Cycle {cycle[0]}, Build {cycle[1]})"
        expected["display_name"] += extra_display
    if extra:
        tag += f"_{extra}"
        expected["display_name"] += f" [{extra}]"
    expected["tag"] = tag

    # Now parse the modified tag and check against the expected output.
    assert RSPImageTag.from_str(tag).to_dict() == expected
