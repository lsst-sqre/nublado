"""Abstract data types for handling RSP image tags."""

import contextlib
import re
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import total_ordering
from typing import Self, TypeGuard

import semver

from .imagefilterpolicy import RSPImageFilterPolicy
from .rspimagetype import RSPImageType

DOCKER_DEFAULT_TAG = "latest"
"""Implicit tag used by Docker/Kubernetes when no tag is specified."""

__all__ = [
    "DOCKER_DEFAULT_TAG",
    "RSPImageTag",
    "RSPImageTagCollection",
    "RSPImageType",
]

# Regular expression components used to construct the parsing regexes.

# r22_0_1
_RELEASE = r"r(?P<major>\d+)_(?P<minor>\d+)_(?P<patch>\d+)"
# r23_0_0_rc1
_CANDIDATE = r"r(?P<major>\d+)_(?P<minor>\d+)_(?P<patch>\d+)_(?P<pre>rc\d+)"
# w_2021_13
_WEEKLY = r"w_(?P<year>\d+)_(?P<week>\d+)"
# d_2021_05_13
_DAILY = r"d_(?P<year>\d+)_(?P<month>\d+)_(?P<day>\d+)"
# exp
_EXPERIMENTAL = r"exp"
# c0020.002
_CYCLE = r"_c(?P<cycle>\d+)\.(?P<cbuild>\d+)"
# rsp19
_RSP = r"_rsp(?P<rspbuild>\d+)"
# recommended_c0020 (used for alias tags)
_UNKNOWN_WITH_CYCLE = r"(?P<tag>.*)_c(?P<cycle>\d+)"
# _whatever_your_little_heart_desires
_REST = r"_(?P<rest>.*)"

# The heart of the parser.  An ordered list of tuples, each of which contains
# a tag type followed by a regular expression defining something that matches
# that type, with named capture groups.
#
# Note that this is matched top to bottom.  In particular, the release
# candidate images must precede the release images since they would otherwise
# parse as a release image with non-empty "rest", and anything with an rsp
# build version tag must precede the same type, but without that tag, or it
# will match a non-empty "rest".
#
_TAG_REGEXES = [
    # r23_0_0_rc1_rsp19_c0020.001_20210513
    (
        RSPImageType.CANDIDATE,
        re.compile(_CANDIDATE + _RSP + _CYCLE + _REST + "$"),
    ),
    # r23_0_0_rc1_rsp19_c0020.001
    (RSPImageType.CANDIDATE, re.compile(_CANDIDATE + _RSP + _CYCLE + "$")),
    # r23_0_0_rc1_rsp19_20210513
    (RSPImageType.CANDIDATE, re.compile(_CANDIDATE + _RSP + _REST + "$")),
    # r23_0_0_rc1_rsp19
    (RSPImageType.CANDIDATE, re.compile(_CANDIDATE + _RSP + "$")),
    # r23_0_0_rc1_c0020.001_20210513
    (RSPImageType.CANDIDATE, re.compile(_CANDIDATE + _CYCLE + _REST + "$")),
    # r23_0_0_rc1_c0020.001
    (RSPImageType.CANDIDATE, re.compile(_CANDIDATE + _CYCLE + "$")),
    # r23_0_0_rc1_20210513
    (RSPImageType.CANDIDATE, re.compile(_CANDIDATE + _REST + "$")),
    # r23_0_0_rc1
    (RSPImageType.CANDIDATE, re.compile(_CANDIDATE + "$")),
    # r22_0_1_rsp19_c0019.001_20210513
    (RSPImageType.RELEASE, re.compile(_RELEASE + _RSP + _CYCLE + _REST + "$")),
    # r22_0_1_rsp_1.2.3_c0019.001
    (RSPImageType.RELEASE, re.compile(_RELEASE + _RSP + _CYCLE + "$")),
    # r22_0_1_rsp19_20210513
    (RSPImageType.RELEASE, re.compile(_RELEASE + _RSP + _REST + "$")),
    # r22_0_1_rsp19
    (RSPImageType.RELEASE, re.compile(_RELEASE + _RSP + "$")),
    # r22_0_1_c0019.001_20210513
    (RSPImageType.RELEASE, re.compile(_RELEASE + _CYCLE + _REST + "$")),
    # r22_0_1_c0019.001
    (RSPImageType.RELEASE, re.compile(_RELEASE + _CYCLE + "$")),
    # r22_0_1_20210513
    (RSPImageType.RELEASE, re.compile(_RELEASE + _REST + "$")),
    # r22_0_1
    (RSPImageType.RELEASE, re.compile(_RELEASE + "$")),
    # r170 (obsolete) (no new ones, no additional parts)
    (RSPImageType.RELEASE, re.compile(r"r(?P<major>\d\d)(?P<minor>\d)$")),
    # w_2021_13_rsp19_c0020.001_20210513
    (RSPImageType.WEEKLY, re.compile(_WEEKLY + _RSP + _CYCLE + _REST + "$")),
    # w_2021_13_rsp19_c0020.001
    (RSPImageType.WEEKLY, re.compile(_WEEKLY + _RSP + _CYCLE + "$")),
    # w_2021_13_rsp19_20210513
    (RSPImageType.WEEKLY, re.compile(_WEEKLY + _RSP + _REST + "$")),
    # w_2021_13_rsp19
    (RSPImageType.WEEKLY, re.compile(_WEEKLY + _RSP + "$")),
    # w_2021_13_c0020.001_20210513
    (RSPImageType.WEEKLY, re.compile(_WEEKLY + _CYCLE + _REST + "$")),
    # w_2021_13_c0020.001
    (RSPImageType.WEEKLY, re.compile(_WEEKLY + _CYCLE + "$")),
    # w_2021_13_20210513
    (RSPImageType.WEEKLY, re.compile(_WEEKLY + _REST + "$")),
    # w_2021_13
    (RSPImageType.WEEKLY, re.compile(_WEEKLY + "$")),
    # d_2021_05_13_rsp19_c0019.001_20210513
    (RSPImageType.DAILY, re.compile(_DAILY + _RSP + _CYCLE + _REST + "$")),
    # d_2021_05_13_rsp19_c0019.001
    (RSPImageType.DAILY, re.compile(_DAILY + _RSP + _CYCLE + "$")),
    # d_2021_05_13_rsp19_20210513
    (RSPImageType.DAILY, re.compile(_DAILY + _RSP + _REST + "$")),
    # d_2021_05_13_rsp19
    (RSPImageType.DAILY, re.compile(_DAILY + _RSP + "$")),
    # d_2021_05_13_c0019.001_20210513
    (RSPImageType.DAILY, re.compile(_DAILY + _CYCLE + _REST + "$")),
    # d_2021_05_13_c0019.001
    (RSPImageType.DAILY, re.compile(_DAILY + _CYCLE + "$")),
    # d_2021_05_13_20210513
    (RSPImageType.DAILY, re.compile(_DAILY + _REST + "$")),
    # d_2021_05_13
    (RSPImageType.DAILY, re.compile(_DAILY + "$")),
    # exp_w_2021_05_13_nosudo
    (RSPImageType.EXPERIMENTAL, re.compile(_EXPERIMENTAL + _REST + "$")),
    # recommended_c0029
    (RSPImageType.UNKNOWN, re.compile(_UNKNOWN_WITH_CYCLE + "$")),
]


@dataclass
class _Minitag:
    """A stripped-down tag class used for convenience in tag parsing."""

    major: str = ""
    minor: str = ""
    patch: str = ""
    pre: str = ""
    display_name: str = ""


@total_ordering
@dataclass
class RSPImageTag:
    """A sortable image tag for a Rubin Science Platform image.

    This class encodes the tag conventions documented in :sqr:`059`.  These
    conventions are specific to the Rubin Science Platform.
    """

    tag: str
    """The tag itself, unmodified."""

    image_type: RSPImageType
    """Type (release series) of image identified by this tag."""

    version: semver.Version | None
    """Version information as a semantic version."""

    rsp_build_version: int | None
    """Version information about the RSP build as a counter."""

    cycle: int | None
    """XML schema version implemented by this image (only for T&S builds)."""

    display_name: str
    """Human-readable display name."""

    date: datetime | None
    """When the image was created, or as close as we can get to that.

    We try to derive this from the tag string: For RSP daily or weekly
    tags (or experimentals in one of those formats), we can calculate
    this to within a day or a week, which is good enough for display
    purposes.  Otherwise, we may be able to extract this info from
    the registry, but even if we can, it may be image upload time
    rather than creation time.
    """

    @classmethod
    def alias(cls, tag: str) -> Self:
        """Create an alias tag.

        Parameters
        ----------
        tag
            Name of the alias tag.

        Returns
        -------
        RSPImageTag
            The corresponding `RSPImageTag`.
        """
        if match := re.match(_UNKNOWN_WITH_CYCLE + "$", tag):
            cycle = int(match.group("cycle"))
            display_name = match.group("tag").replace("_", " ").title()
            display_name += f" (SAL Cycle {match.group('cycle')})"
        else:
            cycle = None
            display_name = tag.replace("_", " ").title()
        return cls(
            tag=tag,
            image_type=RSPImageType.ALIAS,
            version=None,
            rsp_build_version=None,
            cycle=cycle,
            display_name=display_name,
            date=None,
        )

    @classmethod
    def from_str(cls, tag: str) -> Self:
        """Parse a tag into an `RSPImageTag`.

        Parameters
        ----------
        tag
            The tag.

        Returns
        -------
        RSPImageTag
            The corresponding `RSPImageTag` object.
        """
        if not tag:
            tag = DOCKER_DEFAULT_TAG
        for image_type, regex in _TAG_REGEXES:
            match = regex.match(tag)
            if match:
                # It should be impossible for from_match to fail if we
                # constructed the regexes properly, but if it does,
                # silently fall back on treating this as an unknown tag
                # rather than crashing the lab controller.
                with contextlib.suppress(Exception):
                    return cls._from_match(image_type, match, tag)

        # No matches, so return the unknown tag type.
        return cls(
            image_type=RSPImageType.UNKNOWN,
            version=None,
            rsp_build_version=None,
            tag=tag,
            cycle=None,
            display_name=tag,
            date=None,
        )

    def __hash__(self) -> int:
        return hash(self.tag)

    def __eq__(self, other: object) -> bool:
        return self._compare(other) == 0

    def __lt__(self, other: object) -> bool:
        order = self._compare(other)
        if order is NotImplemented:
            return NotImplemented
        return order == -1

    @classmethod
    def _from_match(
        cls, image_type: RSPImageType, match: re.Match, tag: str
    ) -> Self:
        """Create an `RSPImageTag` from a regex match.

        Parameters
        ----------
        image_type
            Identified type of image.
        match
            Match object containing named capture groups.
        tag
            The tag being parsed.

        Returns
        -------
        RSPImageTag
            The corresponding `RSPImageTag` object.
        """
        data = match.groupdict()
        rest = data.get("rest")
        cycle = data.get("cycle")
        cbuild = data.get("cbuild")
        rsp_build_version = cls._extract_rsp_build_version(data)

        # We can't do very much with unknown tags with a cycle, but we do want
        # to capture the cycle so that they survive cycle filtering. We can
        # also format the cycle for display purposes.
        if image_type == RSPImageType.UNKNOWN:
            display_name = data.get("tag", tag)
            if cycle:
                display_name += f" (SAL Cycle {cycle})"
            return cls(
                image_type=image_type,
                version=None,
                rsp_build_version=rsp_build_version,
                tag=tag,
                cycle=int(cycle) if cycle else None,
                display_name=display_name,
                date=None,
            )

        # Experimental tags are often exp_<legal-tag>, meaning that they are
        # an experimental build on top of another tag with additional
        # information in the trailing _rest component.  Therefore, to generate
        # a display name, try to parse the rest of the tag as a valid tag, and
        # extract its display name.
        #
        # If the rest portion of the tag isn't a valid tag, it will turn into
        # an unknown tag, which uses the tag string as its display name, so
        # this will generate a display name of "Experimental <rest>".
        if image_type == RSPImageType.EXPERIMENTAL:
            if rest:
                subtag = cls.from_str(rest)
                display_name = f"{image_type.value} {subtag.display_name}"
            else:
                display_name = image_type.value
            return cls(
                image_type=image_type,
                version=subtag.version,
                rsp_build_version=subtag.rsp_build_version,
                tag=tag,
                cycle=subtag.cycle,
                display_name=display_name,
                date=subtag.date,
            )

        # Determine the build number, the last component of the semantic
        # version, which is the same for all image types.
        build = cls._determine_build(cycle, cbuild, rest)

        minitag = cls._get_minitag(image_type, data)

        version = semver.Version(
            major=int(minitag.major),
            minor=int(minitag.minor),
            patch=int(minitag.patch),
            prerelease=minitag.pre if minitag.pre else None,
            build=build,
        )

        display_name = minitag.display_name

        # If there is extra information, add it to the end of the display name.
        if rsp_build_version:
            display_name += f" (RSP Build {rsp_build_version!s})"
        if cycle:
            display_name += f" (SAL Cycle {cycle}, Build {cbuild})"
        if rest:
            display_name += f" [{rest}]"

        # Return the results.
        return cls(
            image_type=image_type,
            version=version,
            rsp_build_version=rsp_build_version,
            tag=tag,
            cycle=int(cycle) if cycle else None,
            display_name=display_name,
            date=cls._calculate_date(data),
        )

    @classmethod
    def _determine_build(
        cls, cycle: str | None, cbuild: str | None, rest: str | None
    ) -> str | None:
        """Determine the build component of the semantic version.

        Parameters
        ----------
        cycle
            The cycle number, if any.
        cbuild
            The build number within a cycle, if any.
        rest
            Any trailing part of the version.

        Returns
        -------
        str or None
            What to put in the build component of the semantic version.
        """
        # semver build components may only contain periods and alphanumerics,
        # so replace underscores with periods and then remove all other
        # characters.
        if rest:
            rest = re.sub(r"[^\w.]+", "", rest.replace("_", "."))

        # Add on the cycle if one is available.
        if cycle is not None:
            if rest:
                return f"c{cycle}.{cbuild}.{rest}"
            else:
                return f"c{cycle}.{cbuild}"
        else:
            return rest if rest else None

    @classmethod
    def _get_minitag(
        cls, image_type: RSPImageType, tagdata: dict[str, str]
    ) -> _Minitag:
        """Return a text representation of a subset of tag data, for
        help in parsing.
        """
        # The display name starts as the image type and we add more
        # information as we go.
        display_name = image_type.value

        if image_type in (RSPImageType.RELEASE, RSPImageType.CANDIDATE):
            major = tagdata["major"]
            minor = tagdata["minor"]
            patch = tagdata.get("patch", "0")
            pre = tagdata.get("pre", "")
            display_name += f" r{major}.{minor}.{patch}"
            if pre:
                display_name += "-" + pre
        else:
            major = tagdata["year"]
            if image_type == RSPImageType.WEEKLY:
                minor = tagdata["week"]
                patch = "0"
                display_name += f" {major}_{minor}"
            else:
                minor = tagdata["month"]
                patch = tagdata["day"]
                display_name += f" {major}_{minor}_{patch}"
            pre = ""

        return _Minitag(
            major=major,
            minor=minor,
            patch=patch,
            pre=pre,
            display_name=display_name,
        )

    @staticmethod
    def _calculate_date(tagdata: dict[str, str]) -> datetime | None:
        """Calculate the date when the image should have been created.

        Parameters
        ----------
        tagdata
            The match groups from the regular expression tag match.

        Returns
        -------
        datetime.datetime | None
            The image creation date if it can be gleaned from the tag.
        """
        year = tagdata.get("year")
        if not year:
            return None
        week = tagdata.get("week")
        if year and week:
            thursday = 4  # We build on Thursday, which is ISO day 4
            stamp = datetime.fromisocalendar(int(year), int(week), thursday)
            return stamp.replace(tzinfo=UTC)
        month = tagdata.get("month")
        day = tagdata.get("day")
        if not (month and day):
            return None
        return datetime(int(year), int(month), int(day), tzinfo=UTC)

    @staticmethod
    def _extract_rsp_build_version(tagdata: dict[str, str]) -> int | None:
        """Retrieve the rsp version from the tag match, if given.

        It will always be a non-negative integer, if it exists.

        Parameters
        ----------
        tagdata
            The match groups from the regular expression tag match.

        Returns
        -------
        semver.Version | None
            The RSP tag, as a semantic version, if present.
        """
        bld = tagdata.get("rspbuild")
        if bld is None:
            return None
        return int(bld)

    def _compare(self, other: object) -> int:
        """Compare to image tags for sorting purposes.

        Parameters
        ----------
        other
            The other object, potentially an image tag.

        Returns
        -------
        int or NotImplemented
            0 if equal, -1 if self is less than other, 1 if self is greater
            than other, `NotImplemented` if they're not comparable.
        """
        if not self._is_comparable_type(other):
            return NotImplemented

        if not (self.version and other.version):
            if self.tag == other.tag:
                return 0
            return -1 if self.tag < other.tag else 1
        rank = self.version.compare(other.version)
        if rank != 0:
            return rank

        # If we have two tags with the same version, we should next check
        # the RSP version.  If it doesn't exist, it should sort as a lower
        # version than anything with an RSP version tag, to preserve backwards-
        # compatibility.

        rank = self._compare_rsp_build_versions(other)
        if rank != 0:
            return rank

        # semver ignores the build for sorting purposes, but we don't want to
        # since we want newer cycles to sort ahead of older cycles (and newer
        # cycle builds to sort above older cycle builds) in otherwise matching
        # tags, and the cycle information is stored in the build.
        return self._compare_build_versions(self.version, other.version)

    def _is_comparable_type(self, other: object) -> TypeGuard[Self]:
        if not isinstance(other, RSPImageTag):
            return False
        return self.image_type == other.image_type

    def _compare_rsp_build_versions(self, other: Self) -> int:
        if self.rsp_build_version == other.rsp_build_version:
            return 0
        if self.rsp_build_version is None:
            return -1
        elif other.rsp_build_version is None:
            return 1
        else:
            return (
                -1 if (self.rsp_build_version < other.rsp_build_version) else 1
            )

    @staticmethod
    def _compare_build_versions(
        self_v: semver.Version, other_v: semver.Version
    ) -> int:
        if self_v.build == other_v.build:
            return 0
        if self_v.build is None:
            return -1
        elif other_v.build is None:
            return 1
        else:
            return -1 if self_v.build < other_v.build else 1


class RSPImageTagCollection:
    """Hold and perform operations on a set of `RSPImageTag` objects.

    Parameters
    ----------
    tags
        `RSPImageTag` objects to store.
    """

    @classmethod
    def from_tag_names(
        cls,
        tag_names: list[str],
        aliases: set[str],
        cycle: int | None = None,
    ) -> Self:
        """Create a collection from tag strings.

        Parameters
        ----------
        tag_names
            Tag strings that should be parsed as tags.
        aliases
            Tags by these names, if found, should be treated as aliases.
        cycle
            If given, only add tags with a matching cycle.

        Returns
        -------
        RSPImageTagCollection
            The resulting collection of tags.
        """
        tags = []
        for name in tag_names:
            if name in aliases:
                tag = RSPImageTag.alias(name)
            else:
                tag = RSPImageTag.from_str(name)
            if cycle is None or tag.cycle == cycle:
                tags.append(tag)
        return cls(tags)

    def __init__(self, tags: Iterable[RSPImageTag]) -> None:
        self._by_tag = {}
        self._by_type = defaultdict(list)
        for tag in tags:
            self._by_tag[tag.tag] = tag
            self._by_type[tag.image_type].append(tag)
        for tag_list in self._by_type.values():
            tag_list.sort(reverse=True)

    def all_tags(self) -> Iterator[RSPImageTag]:
        """Iterate over all tags.

        Yields
        ------
        RSPImageTag
            Each tag in sorted order.
        """
        for image_type in RSPImageType:
            yield from self._by_type[image_type]

    def tag_for_tag_name(self, tag_name: str) -> RSPImageTag | None:
        """Look up a tag by tag name.

        Parameters
        ----------
        tag_name
            Tag to search for.

        Returns
        -------
        bool
            The tag if found in the collection, else `None`.
        """
        return self._by_tag.get(tag_name)

    def subset(
        self,
        *,
        releases: int = 0,
        weeklies: int = 0,
        dailies: int = 0,
        include: set[str] | None = None,
    ) -> Self:
        """Return a subset of the tag collection.

        Parameters
        ----------
        releases
            Number of releases to include.
        weeklies
            Number of weeklies to include.
        dailies
            Number of dailies to include.
        include
            Include this list of tags even if they don't meet other criteria.

        Returns
        -------
        RSPImageTagCollection
            The desired subset.
        """
        tags = []

        # Extract the desired tag types.
        if releases and RSPImageType.RELEASE in self._by_type:
            tags.extend(self._by_type[RSPImageType.RELEASE][0:releases])
        if weeklies and RSPImageType.WEEKLY in self._by_type:
            tags.extend(self._by_type[RSPImageType.WEEKLY][0:weeklies])
        if dailies and RSPImageType.DAILY in self._by_type:
            tags.extend(self._by_type[RSPImageType.DAILY][0:dailies])

        # Include additional tags if they're present in the collection.
        if include:
            tags.extend(
                [self._by_tag[t] for t in include if t in self._by_tag]
            )

        # Return the results.
        return type(self)(tags)

    def filter(
        self, policy: RSPImageFilterPolicy, age_basis: datetime
    ) -> list[RSPImageTag]:
        """Apply a filter policy and return the remaining tags.

        Parameters
        ----------
        policy
            Policy governing tag filtering.
        age_basis
            Timestamp to use as basis for image age calculation.

        Returns
        -------
        list[RSPImageTag]
            Tags remaining after policy application.
        """
        tags: list[RSPImageTag] = []
        for category in RSPImageType:
            tags.extend(
                self._apply_category_policy(policy, category, age_basis)
            )
        return tags

    def _apply_category_policy(
        self,
        policy: RSPImageFilterPolicy,
        category: RSPImageType,
        age_basis: datetime,
    ) -> list[RSPImageTag]:
        candidates = list(self._by_type[category])
        remainder: list[RSPImageTag] = []
        cat_policy = policy.policy_for_category(category)
        if cat_policy is None:
            return candidates
        cutoff_date: datetime | None = None
        if cat_policy.age is not None:
            cutoff_date = age_basis - cat_policy.age
        cutoff_version: semver.Version | None = None
        if cat_policy.cutoff_version is not None:
            cutoff_version = semver.Version.parse(cat_policy.cutoff_version)
        for tag in candidates:
            if cat_policy.number is not None and cat_policy.number <= len(
                remainder
            ):
                break
            if tag.date is not None and cutoff_date is not None:
                if tag.date < cutoff_date:
                    continue
            if tag.version is not None and cutoff_version is not None:
                if tag.version < cutoff_version:
                    continue
            remainder.append(tag)
        return remainder
