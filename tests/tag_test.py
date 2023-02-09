"""Tests of Docker image tag analysis and deduplication."""

from __future__ import annotations

from semver import VersionInfo

from jupyterlabcontroller.models.tag import RSPTagType, StandaloneRSPTag


def test_parse_tag() -> None:
    """Parse tags into StandaloneRSPTag objects."""
    test_cases = {
        "r21_0_1": StandaloneRSPTag(
            tag="r21_0_1",
            image_type=RSPTagType.RELEASE,
            display_name="Release r21.0.1",
            semantic_version=VersionInfo(21, 0, 1),
            cycle=None,
        ),
        "r22_0_0_rc1": StandaloneRSPTag(
            tag="r22_0_0_rc1",
            image_type=RSPTagType.RELEASE_CANDIDATE,
            display_name="Release Candidate r22.0.0-rc1",
            semantic_version=VersionInfo(22, 0, 0, "rc1"),
            cycle=None,
        ),
        "w_2021_22": StandaloneRSPTag(
            tag="w_2021_22",
            image_type=RSPTagType.WEEKLY,
            display_name="Weekly 2021_22",
            semantic_version=VersionInfo(2021, 22, 0),
            cycle=None,
        ),
        "d_2021_05_27": StandaloneRSPTag(
            tag="d_2021_05_27",
            image_type=RSPTagType.DAILY,
            display_name="Daily 2021_05_27",
            semantic_version=VersionInfo(2021, 5, 27),
            cycle=None,
        ),
        "r21_0_1_c0020.001": StandaloneRSPTag(
            tag="r21_0_1_c0020.001",
            image_type=RSPTagType.RELEASE,
            display_name="Release r21.0.1 (SAL Cycle 0020, Build 001)",
            semantic_version=VersionInfo(21, 0, 1, None, "c0020.001"),
            cycle=20,
        ),
        "r22_0_0_rc1_c0020.001": StandaloneRSPTag(
            tag="r22_0_0_rc1_c0020.001",
            image_type=RSPTagType.RELEASE_CANDIDATE,
            display_name=(
                "Release Candidate r22.0.0-rc1 (SAL Cycle 0020, Build 001)"
            ),
            semantic_version=VersionInfo(22, 0, 0, "rc1", "c0020.001"),
            cycle=20,
        ),
        "w_2021_22_c0020.001": StandaloneRSPTag(
            tag="w_2021_22_c0020.001",
            image_type=RSPTagType.WEEKLY,
            display_name="Weekly 2021_22 (SAL Cycle 0020, Build 001)",
            semantic_version=VersionInfo(2021, 22, 0, None, "c0020.001"),
            cycle=20,
        ),
        "d_2021_05_27_c0020.001": StandaloneRSPTag(
            tag="d_2021_05_27_c0020.001",
            image_type=RSPTagType.DAILY,
            display_name="Daily 2021_05_27 (SAL Cycle 0020, Build 001)",
            semantic_version=VersionInfo(2021, 5, 27, None, "c0020.001"),
            cycle=20,
        ),
        "r21_0_1_20210527": StandaloneRSPTag(
            tag="r21_0_1_20210527",
            image_type=RSPTagType.RELEASE,
            display_name="Release r21.0.1 [20210527]",
            semantic_version=VersionInfo(21, 0, 1, None, "20210527"),
            cycle=None,
        ),
        "r22_0_0_rc1_20210527": StandaloneRSPTag(
            tag="r22_0_0_rc1_20210527",
            image_type=RSPTagType.RELEASE_CANDIDATE,
            display_name="Release Candidate r22.0.0-rc1 [20210527]",
            semantic_version=VersionInfo(22, 0, 0, "rc1", "20210527"),
            cycle=None,
        ),
        "w_2021_22_20210527": StandaloneRSPTag(
            tag="w_2021_22_20210527",
            image_type=RSPTagType.WEEKLY,
            display_name="Weekly 2021_22 [20210527]",
            semantic_version=VersionInfo(2021, 22, 0, None, "20210527"),
            cycle=None,
        ),
        "d_2021_05_27_20210527": StandaloneRSPTag(
            tag="d_2021_05_27_20210527",
            image_type=RSPTagType.DAILY,
            display_name="Daily 2021_05_27 [20210527]",
            semantic_version=VersionInfo(2021, 5, 27, None, "20210527"),
            cycle=None,
        ),
        "r21_0_1_c0020.001_20210527": StandaloneRSPTag(
            tag="r21_0_1_c0020.001_20210527",
            image_type=RSPTagType.RELEASE,
            display_name=(
                "Release r21.0.1 (SAL Cycle 0020, Build 001) [20210527]"
            ),
            semantic_version=VersionInfo(21, 0, 1, None, "c0020.001.20210527"),
            cycle=20,
        ),
        "r22_0_0_rc1_c0020.001_20210527": StandaloneRSPTag(
            tag="r22_0_0_rc1_c0020.001_20210527",
            image_type=RSPTagType.RELEASE_CANDIDATE,
            display_name=(
                "Release Candidate r22.0.0-rc1 (SAL Cycle 0020, Build 001)"
                " [20210527]"
            ),
            semantic_version=VersionInfo(
                22, 0, 0, "rc1", "c0020.001.20210527"
            ),
            cycle=20,
        ),
        "w_2021_22_c0020.001_20210527": StandaloneRSPTag(
            tag="w_2021_22_c0020.001_20210527",
            image_type=RSPTagType.WEEKLY,
            display_name=(
                "Weekly 2021_22_ (SAL Cycle 0020, Build 001) [20210527]"
            ),
            semantic_version=VersionInfo(
                2021, 22, 0, None, "c0020.001.20210527"
            ),
            cycle=20,
        ),
        "d_2021_05_27_c0020.001_20210527": StandaloneRSPTag(
            tag="d_2021_05_27_c0020.001_20210527",
            image_type=RSPTagType.DAILY,
            display_name=(
                "Daily 2021_05_27 (SAL Cycle 0020, Build 001) [20210527]"
            ),
            semantic_version=VersionInfo(
                2021, 5, 27, None, "c0020.001.20210527"
            ),
            cycle=20,
        ),
        "recommended": StandaloneRSPTag(
            tag="recommended",
            image_type=RSPTagType.UNKNOWN,
            display_name="recommended",
            semantic_version=None,
            cycle=None,
        ),
        "exp_random": StandaloneRSPTag(
            tag="exp_random",
            image_type=RSPTagType.EXPERIMENTAL,
            display_name="Experimental random",
            semantic_version=None,
            cycle=None,
        ),
        "exp_w_2021_22": StandaloneRSPTag(
            tag="exp_w_2021_22",
            image_type=RSPTagType.EXPERIMENTAL,
            display_name="Experimental Weekly 2021_22",
            semantic_version=None,
            cycle=None,
        ),
        "not_a_normal_format": StandaloneRSPTag(
            tag="not_a_normal_format",
            image_type=RSPTagType.UNKNOWN,
            display_name="not_a_normal_format",
            semantic_version=None,
            cycle=None,
        ),
        "MiXeD_CaSe_TaG": StandaloneRSPTag(
            tag="MiXeD_CaSe_TaG",
            image_type=RSPTagType.UNKNOWN,
            display_name="MiXeD_CaSe_TaG",
            semantic_version=None,
            cycle=None,
        ),
    }

    for tag, expected in test_cases.items():
        assert StandaloneRSPTag.parse_tag(tag) == expected
