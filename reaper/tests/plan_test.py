"""Test planning which images to delete."""

from copy import deepcopy

from safir.datetime import parse_timedelta as pt

from reaper.config import (
    IndividualKeepPolicy,
    KeepPolicy,
    RegistryConfig,
    RSPKeepers,
)
from reaper.services.reaper import Reaper


def test_plan_count(ghcr_cfg: RegistryConfig) -> None:
    """Plan based on a number-based keep policy."""
    new_cfg = deepcopy(ghcr_cfg)
    kp = KeepPolicy(
        semver=None,
        untagged=IndividualKeepPolicy(number=0),
        rsp=RSPKeepers(
            release=IndividualKeepPolicy(number=3),
            weekly=IndividualKeepPolicy(number=10),
            daily=IndividualKeepPolicy(number=15),
            release_candidate=IndividualKeepPolicy(number=1),
            experimental=IndividualKeepPolicy(number=3),
            unknown=IndividualKeepPolicy(number=0),
        ),
    )
    new_cfg.keep = kp
    r = Reaper(cfg=new_cfg)
    r.populate()
    r.plan()
    remainder = r.remaining()
    assert len(remainder.untagged) == 0
    assert len(remainder.rsp["release"]) == 3
    assert len(remainder.rsp["weekly"]) == 10
    assert len(remainder.rsp["daily"]) == 15
    assert len(remainder.rsp["release_candidate"]) == 1
    assert len(remainder.rsp["experimental"]) == 3
    assert len(remainder.rsp["unknown"]) == 0


def test_plan_count_surplus(ghcr_cfg: RegistryConfig) -> None:
    """Plan based on a number-based keep policy with numbers larger than
    the actual image count.
    """
    new_cfg = deepcopy(ghcr_cfg)
    kp = KeepPolicy(
        semver=None,
        untagged=IndividualKeepPolicy(number=9999),
        rsp=RSPKeepers(
            release=IndividualKeepPolicy(number=9999),
            weekly=IndividualKeepPolicy(number=9999),
            daily=IndividualKeepPolicy(number=9999),
            release_candidate=IndividualKeepPolicy(number=9999),
            experimental=IndividualKeepPolicy(number=9999),
            unknown=IndividualKeepPolicy(number=9999),
        ),
    )
    new_cfg.keep = kp
    r = Reaper(cfg=new_cfg)
    r.populate()
    r.plan()
    remainder = r.remaining()
    initial = r._categorized
    assert len(remainder.untagged) == len(initial.untagged)
    assert len(remainder.rsp["release"]) == len(initial.rsp["release"])
    assert len(remainder.rsp["weekly"]) == len(initial.rsp["weekly"])
    assert len(remainder.rsp["daily"]) == len(initial.rsp["daily"])
    assert len(remainder.rsp["release_candidate"]) == len(
        initial.rsp["release_candidate"]
    )
    assert len(remainder.rsp["experimental"]) == len(initial.rsp["experimental"])
    assert len(remainder.rsp["unknown"]) == len(initial.rsp["unknown"])


def test_plan_count_time(ghcr_cfg: RegistryConfig) -> None:
    """Plan based on a time-based keep policy.

    Since we don't know how far into the future we will run the tests,
    we're going to set the time to zero, and see if we plan to
    reap all images.
    """
    new_cfg = deepcopy(ghcr_cfg)
    kp = KeepPolicy(
        semver=None,
        untagged=IndividualKeepPolicy(age=pt("0s")),
        rsp=RSPKeepers(
            release=IndividualKeepPolicy(age=pt("0s")),
            weekly=IndividualKeepPolicy(age=pt("0s")),
            daily=IndividualKeepPolicy(age=pt("0s")),
            release_candidate=IndividualKeepPolicy(age=pt("0s")),
            experimental=IndividualKeepPolicy(age=pt("0s")),
            unknown=IndividualKeepPolicy(age=pt("0s")),
        ),
    )
    new_cfg.keep = kp
    r = Reaper(cfg=new_cfg)
    r.populate()
    r.plan()
    remainder = r.remaining()
    assert len(remainder.untagged) == 0
    assert len(remainder.rsp["release"]) == 0
    assert len(remainder.rsp["weekly"]) == 0
    assert len(remainder.rsp["daily"]) == 0
    assert len(remainder.rsp["release_candidate"]) == 0
    assert len(remainder.rsp["experimental"]) == 0
    assert len(remainder.rsp["unknown"]) == 0


def test_plan_mixed(ghcr_cfg: RegistryConfig) -> None:
    """Plan based on a mixed keep policy.

    Since we don't know how far into the future we will run the tests,
    we're going to set the time to something that will reap at least some
    (and maybe all) images.
    """
    new_cfg = deepcopy(ghcr_cfg)
    kp = KeepPolicy(
        semver=None,
        untagged=IndividualKeepPolicy(number=0),
        rsp=RSPKeepers(
            release=IndividualKeepPolicy(age=pt("180d")),
            weekly=IndividualKeepPolicy(number=13),
            daily=IndividualKeepPolicy(number=25),
            release_candidate=IndividualKeepPolicy(age=pt("90d")),
            experimental=IndividualKeepPolicy(number=4),
            unknown=IndividualKeepPolicy(number=0),
        ),
    )
    new_cfg.keep = kp
    r = Reaper(cfg=new_cfg)
    r.populate()
    r.plan()
    remainder = r.remaining()
    initial = r._categorized
    assert len(remainder.untagged) == 0
    assert len(remainder.rsp["release"]) < len(initial.rsp["release"])
    assert len(remainder.rsp["weekly"]) == 13
    assert len(remainder.rsp["daily"]) == 25
    assert len(remainder.rsp["release_candidate"]) < len(
        initial.rsp["release_candidate"]
    )
    assert len(remainder.rsp["experimental"]) == 4
    assert len(remainder.rsp["unknown"]) == 0


def test_which_victims(ghcr_cfg: RegistryConfig) -> None:
    """Plan based on a number-based keep policy."""
    new_cfg = deepcopy(ghcr_cfg)
    kp = KeepPolicy(
        semver=None,
        untagged=IndividualKeepPolicy(number=0),
        rsp=RSPKeepers(
            release=IndividualKeepPolicy(number=3),
            weekly=IndividualKeepPolicy(number=10),
            daily=IndividualKeepPolicy(number=15),
            release_candidate=IndividualKeepPolicy(number=1),
            experimental=IndividualKeepPolicy(number=3),
            unknown=IndividualKeepPolicy(number=0),
        ),
    )
    new_cfg.keep = kp
    r = Reaper(cfg=new_cfg)
    r.populate()
    r.plan()
    remainder = r.remaining()
    initial = r._categorized

    weeklies = list(initial.rsp["weekly"].values())
    new_weekly = weeklies[0].digest
    old_weekly = weeklies[-1].digest

    assert new_weekly in remainder.rsp["weekly"]
    assert old_weekly not in remainder.rsp["weekly"]
    assert r._plan is not None
    assert new_weekly not in r._plan
    assert old_weekly in r._plan


def test_skip_tags(ghcr_cfg: RegistryConfig) -> None:
    """Test that skipping requested tags works."""
    new_cfg = deepcopy(ghcr_cfg)
    kp = KeepPolicy(
        semver=None,
        untagged=IndividualKeepPolicy(number=0),
        rsp=RSPKeepers(
            release=IndividualKeepPolicy(number=0),
            weekly=IndividualKeepPolicy(number=0),
            daily=IndividualKeepPolicy(number=0),
            release_candidate=IndividualKeepPolicy(number=0),
            experimental=IndividualKeepPolicy(number=0),
            unknown=IndividualKeepPolicy(number=0),
        ),
    )
    new_cfg.keep = kp
    r = Reaper(cfg=new_cfg)
    r.populate()
    r.plan()
    remainder = r.remaining()
    assert len(remainder.rsp["weekly"]) == 0
    initial = r._categorized
    assert len(initial.rsp["weekly"]) > 0
    tag = ""
    # Find the first weekly tag, and exclude it from consideration.
    for img in initial.rsp["weekly"].values():
        for t in img.tags:
            if t.startswith("w_"):
                tag = t
                break
    assert tag != ""
    r._skip_tags = {tag}
    r.plan()
    remainder = r.remaining()
    assert len(remainder.rsp["weekly"]) == 1
    for img in remainder.rsp["weekly"].values():
        assert img.tags & r._skip_tags
        assert tag in img.tags
