"""Abstract data types for handling RSP image tags."""

import contextlib
import re
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import total_ordering
from typing import Any, Self, TypeGuard, override

from safir.datetime import format_datetime_for_logging
from semver import Version

from .imagefilterpolicy import ImageFilterPolicy, RSPImageFilterPolicy
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
# exp_
_EXPERIMENTAL = r"exp_(?P<rest>.*)"
# recommended_c0020 (used for alias tags)
_UNKNOWN_WITH_CYCLE = r"(?P<tag>.*)_c(?P<cycle>\d+)"
# c0020.002
_CYCLE = r"(?:_c(?P<cycle>\d+)\.(?P<cbuild>\d+))?"
# rsp19
_RSP = r"(?:_rsp(?P<rspbuild>\d+))?"
# _whatever_your_heart_desires (non-greedy since architecture may follow)
_REST = r"(?:_(?P<rest>.*?))?"
# -amd64 or -arm64
_ARCH = r"(?:-(?P<arch>[a-z0-9]+))?"

# An ordered list of tuples, each of which contains a tag type followed by a
# regular expression defining something that matches that type, with named
# capture groups. The _RSP, _CYCLE, and _REST capture groups are optional and
# will be attempted in that order.
#
# A tag is matched against these regular expressions in order. The release
# candidate images must precede the release images, since they would otherwise
# parse as a release image with non-empty "rest".
_TAG_REGEXES = [
    # r23_0_0_rc1_rsp19_c0020.001_20210513
    (
        RSPImageType.CANDIDATE,
        re.compile(_CANDIDATE + _RSP + _CYCLE + _REST + _ARCH + "$"),
    ),
    # r22_0_1_rsp19_c0019.001_20210513
    (
        RSPImageType.RELEASE,
        re.compile(_RELEASE + _RSP + _CYCLE + _REST + _ARCH + "$"),
    ),
    # r170 (obsolete) (no new ones, no additional parts)
    (RSPImageType.RELEASE, re.compile(r"r(?P<major>\d\d)(?P<minor>\d)$")),
    # w_2021_13_rsp19_c0020.001_20210513
    (
        RSPImageType.WEEKLY,
        re.compile(_WEEKLY + _RSP + _CYCLE + _REST + _ARCH + "$"),
    ),
    # d_2021_05_13_rsp19_c0019.001_20210513
    (
        RSPImageType.DAILY,
        re.compile(_DAILY + _RSP + _CYCLE + _REST + _ARCH + "$"),
    ),
    # exp_w_2021_05_13_nosudo
    (RSPImageType.EXPERIMENTAL, re.compile(_EXPERIMENTAL + "$")),
    # recommended_c0029
    (RSPImageType.UNKNOWN, re.compile(_UNKNOWN_WITH_CYCLE + "$")),
]


@total_ordering
@dataclass(kw_only=True)
class RSPImageTag:
    """A sortable image tag for a Rubin Science Platform image.

    This class encodes the tag conventions documented in :sqr:`059`.  These
    conventions are specific to the Rubin Science Platform.
    """

    tag: str
    """The tag itself, unmodified."""

    image_type: RSPImageType
    """Type (release series) of image identified by this tag."""

    display_name: str
    """Human-readable display name."""

    version: Version | None = None
    """Version information as a semantic version."""

    cycle: int | None = None
    """XML schema version implemented by this image (only for T&S builds)."""

    cycle_build: int | None = None
    """XML schema build number (only for T&S builds)."""

    rsp_build: int | None = None
    """Version number of the RSP build machinery."""

    architecture: str | None = None
    """Architecture of image, if specified."""

    extra: str | None = None
    """Additional information about the image."""

    date: datetime | None = None
    """When the image was created, or as close as we can get to that.

    For daily or weekly tags, this can be calculated within a day or week,
    which is good enough for filtering purposes. Other images are not handled
    for now, since the upload time is not necessarily when the image was
    created.
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
            cycle = match.group("cycle")
            display_name = match.group("tag").replace("_", " ").title()
            display_name += f" (SAL Cycle {cycle})"
        else:
            cycle = None
            display_name = tag.replace("_", " ").title()
        return cls(
            tag=tag,
            image_type=RSPImageType.ALIAS,
            display_name=display_name,
            cycle=int(cycle) if cycle else None,
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
        return cls(tag=tag, image_type=RSPImageType.UNKNOWN, display_name=tag)

    @override
    def __hash__(self) -> int:
        return hash(self.tag)

    @override
    def __eq__(self, other: object) -> bool:
        return self._compare(other) == 0

    def __lt__(self, other: object) -> bool:
        order = self._compare(other)
        if order is NotImplemented:
            return NotImplemented
        return order == -1

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dictionary representation.

        This method is used primarily for easy testing to allow comparisons
        with expected JSON output files.
        """
        return {
            "tag": self.tag,
            "image_type": self.image_type.value,
            "display_name": self.display_name,
            "version": self.version.to_dict() if self.version else None,
            "cycle": self.cycle,
            "cycle_build": self.cycle_build,
            "rsp_build": self.rsp_build,
            "architecture": self.architecture,
            "extra": self.extra,
            "date": format_datetime_for_logging(self.date),
        }

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
        cycle = data.get("cycle")
        cycle_build = data.get("cbuild")
        rsp_build = data.get("rspbuild")
        extra = data.get("rest")
        architecture = data.get("arch")

        # We can't do very much with unknown tags with a cycle, but we do want
        # to capture the cycle so that they survive cycle filtering. We can
        # also format the cycle for display purposes.
        if image_type == RSPImageType.UNKNOWN:
            display_name = data.get("tag", tag)
            if cycle:
                display_name += f" (SAL Cycle {cycle})"
            return cls(
                tag=tag,
                image_type=image_type,
                display_name=display_name,
                cycle=int(cycle) if cycle else None,
            )

        # Experimental tags are often exp_<legal-tag>, meaning that they are
        # an experimental build on top of another tag with additional
        # information in the trailing _rest component. Therefore, to generate
        # a display name, try to parse the rest of the tag as a valid tag, and
        # extract its display name.
        #
        # If the extra portion of the tag isn't a valid tag, it will turn into
        # an unknown tag, which uses the tag string as its display name. This
        # will correctly generate a display name of "Experimental <rest>".
        if image_type == RSPImageType.EXPERIMENTAL:
            if not extra:
                raise RuntimeError("Invalid experimental tag match")
            subtag = cls.from_str(extra)
            subtag.image_type = image_type
            subtag.tag = tag
            subtag.display_name = f"{image_type.value} {subtag.display_name}"
            return subtag

        # Parse the remaining version information into a display name and a
        # semantic version.
        display_name, version = cls._parse_version(image_type, data)

        # If there is extra information, add it to the end of the display name.
        if rsp_build:
            display_name += f" (RSP Build {rsp_build})"
        if cycle:
            display_name += f" (SAL Cycle {cycle}, Build {cycle_build})"
        if extra:
            display_name += f" [{extra}]"
        if architecture:
            display_name += f" [{architecture}]"

        # Return the results.
        return cls(
            tag=tag,
            image_type=image_type,
            display_name=display_name,
            version=version,
            cycle=int(cycle) if cycle else None,
            cycle_build=int(cycle_build) if cycle_build else None,
            rsp_build=int(rsp_build) if rsp_build else None,
            architecture=architecture,
            extra=extra,
            date=cls._calculate_date(data),
        )

    @staticmethod
    def _calculate_date(data: dict[str, str]) -> datetime | None:
        """Calculate the date when the image should have been created.

        Parameters
        ----------
        data
            The match groups from the regular expression tag match.

        Returns
        -------
        datetime.datetime | None
            The image creation date if it can be gleaned from the tag.
        """
        year = data.get("year")
        if not year:
            return None
        week = data.get("week")
        if year and week:
            thursday = 4  # We build on Thursday, which is ISO day 4
            stamp = datetime.fromisocalendar(int(year), int(week), thursday)
            return stamp.replace(tzinfo=UTC)
        month = data.get("month")
        day = data.get("day")
        if not (month and day):
            return None
        return datetime(int(year), int(month), int(day), tzinfo=UTC)

    @classmethod
    def _parse_version(
        cls, image_type: RSPImageType, data: dict[str, str]
    ) -> tuple[str, Version]:
        """Turn the regex parse results into a display name and version.

        Parameters
        ----------
        image_type
            Determined type of the image.
        data
            Match group information from the regex.

        Returns
        -------
        str
            Display name.
        Version
            Semantic version.
        """
        # Start off the display name with the image type.
        display_name = image_type.value

        # What match groups are available depend on the type of tag.
        if image_type in (RSPImageType.RELEASE, RSPImageType.CANDIDATE):
            major = int(data["major"])
            minor = int(data["minor"])
            patch = int(data.get("patch", "0"))
            pre = data.get("pre")
            display_name += f" r{major}.{minor}.{patch}"
            if pre:
                display_name += "-" + pre
        else:
            year = data["year"]
            major = int(year)
            pre = None
            if image_type == RSPImageType.WEEKLY:
                week = data["week"]
                display_name += f" {year}_{week}"
                minor = int(week)
                patch = 0
            else:
                month = data["month"]
                day = data["day"]
                display_name += f" {year}_{month}_{day}"
                minor = int(month)
                patch = int(day)

        # Build a semantic version and return it and the constructed display
        # name.
        version = Version(
            major=major, minor=minor, patch=patch, prerelease=pre
        )
        return display_name, version

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

        # If either tag has no semantic version, compare the tag strings.
        # Since the tags have to be the same type, generally if one has no
        # semantic version, the other will not as well, since they'll both be
        # alias tags, unknown tags, or the like.
        if not (self.version and other.version):
            return self._compare_str(self.tag, other.tag)

        # Otherwise, compare the semantic versions. If the semantic versions
        # are equal, compare the RSP build, cycle, cycle build, extra
        # information, and architecture in that order. (This is probably
        # wrong: The cycle should take precedence over the RSP build. In
        # practice, we don't use both at the same time.)
        #
        # For the architecture, sort images without an architecture after
        # images with one so that in the menu, where images are displayed in
        # reverse sorted order, the generic images are first.
        if rank := self.version.compare(other.version):
            return rank
        if rank := self._compare_int(self.rsp_build, other.rsp_build):
            return rank
        if rank := self._compare_int(self.cycle, other.cycle):
            return rank
        if rank := self._compare_int(self.cycle_build, other.cycle_build):
            return rank
        if rank := self._compare_str(self.extra, other.extra):
            return rank
        return self._compare_str(
            self.architecture, other.architecture, none_last=True
        )

    def _is_comparable_type(self, other: object) -> TypeGuard[Self]:
        """Check if the other image tag is comparable.

        Only two image tags of the same underlying type can be compared.
        """
        if not isinstance(other, RSPImageTag):
            return False
        return self.image_type == other.image_type

    def _compare_int(self, left: int | None, right: int | None) -> int:
        """Compare two integers that may be none."""
        if left == right:
            return 0
        if left is None:
            return -1
        if right is None:
            return 1
        return -1 if left < right else 1

    def _compare_str(
        self, left: str | None, right: str | None, *, none_last: bool = False
    ) -> int:
        """Compare two strings that may be none."""
        if left == right:
            return 0
        if left is None:
            return 1 if none_last else -1
        if right is None:
            return -1 if none_last else 1
        return -1 if left < right else 1


class RSPImageTagCollection[T: RSPImageTag]:
    """Hold and perform operations on a set of `RSPImageTag` objects.

    Parameters
    ----------
    tags
        `RSPImageTag` objects to store.
    """

    @classmethod
    def from_tag_names(
        cls,
        tag_names: Iterable[str],
        aliases: set[str],
        cycle: int | None = None,
    ) -> RSPImageTagCollection[RSPImageTag]:
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
        return RSPImageTagCollection[RSPImageTag](tags)

    def __init__(self, tags: Iterable[T]) -> None:
        self._by_tag = {}
        self._by_type = defaultdict(list)
        for tag in tags:
            self._by_tag[tag.tag] = tag
            self._by_type[tag.image_type].append(tag)
        for tag_list in self._by_type.values():
            tag_list.sort(reverse=True)

    def add(self, tag: T) -> None:
        """Add a tag to the collection.

        Parameters
        ----------
        tag
            The tag to add.
        """
        self._by_tag[tag.tag] = tag
        self._by_type[tag.image_type].append(tag)
        self._by_type[tag.image_type].sort(reverse=True)

    def all_tags(self, *, hide_arch_specific: bool = True) -> Iterator[T]:
        """Iterate over all tags.

        Parameters
        ----------
        hide_arch_specific
            If `True`, hide tags for a specific architecture and only include
            tags for all supported architectures.

        Yields
        ------
        RSPImageTag
            Each tag in sorted order.
        """
        for image_type in RSPImageType:
            for tag in self._by_type[image_type]:
                if hide_arch_specific and tag.architecture:
                    continue
                yield tag

    def filter(
        self,
        policy: RSPImageFilterPolicy,
        age_basis: datetime,
        *,
        remove_arch_specific: bool = True,
    ) -> Iterator[T]:
        """Apply a filter policy and return the remaining tags.

        Parameters
        ----------
        policy
            Policy governing tag filtering.
        age_basis
            Timestamp to use as basis for image age calculation.
        remove_arch_specific
            If `True`, remove tags for a specific architecture and only
            include tags for all supported architectures.

        Yields
        ------
        RSPImageTag
            Next tag allowed under the policy.
        """
        for image_type in RSPImageType:
            yield from self._filter_image_list(
                self._by_type[image_type],
                policy.policy_for_image_type(image_type),
                age_basis,
                remove_arch_specific=remove_arch_specific,
            )

    def latest(self, image_type: RSPImageType) -> T | None:
        """Get the latest tag of a given type.

        Parameters
        ----------
        image_type
            Image type to retrieve.

        Returns
        -------
        RSPImageTag or None
            Latest tag of that type, if any.
        """
        tags = self._by_type[image_type]
        return tags[0] if tags else None

    def subset(
        self,
        *,
        releases: int = 0,
        weeklies: int = 0,
        dailies: int = 0,
        include: set[str] | None = None,
        remove_arch_specific: bool = True,
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
        remove_arch_specific
            If `True`, remove tags for a specific architecture and only
            include tags for all supported architectures.

        Returns
        -------
        RSPImageTagCollection
            The desired subset.
        """
        tags: list[T] = []

        # Extract the desired tag types.
        args = {"remove_arch_specific": remove_arch_specific}
        tags.extend(self._first_tags(RSPImageType.RELEASE, releases, **args))
        tags.extend(self._first_tags(RSPImageType.WEEKLY, weeklies, **args))
        tags.extend(self._first_tags(RSPImageType.DAILY, dailies, **args))

        # Include additional tags if they're present in the collection.
        if include:
            partial = (self._by_tag[t] for t in include if t in self._by_tag)
            tags.extend(partial)

        # Return the results.
        return type(self)(tags)

    def tag_for_tag_name(self, tag_name: str) -> T | None:
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

    def _filter_image_list(
        self,
        tags: list[T],
        policy: ImageFilterPolicy | None,
        age_basis: datetime,
        *,
        remove_arch_specific: bool = True,
    ) -> Iterator[T]:
        """Filter a list of tags against a filter policy.

        Parameters
        ----------
        tags
            List of tags to filter.
        policy
            Image filter policy to apply, or `None` to do no filtering.
        age_basis
            Current time to use as a basis for age filters.
        remove_arch_specific
            If `True`, remove tags for a specific architecture and only
            include tags for all supported architectures.
        """
        if not policy:
            yield from iter(tags)
            return
        date = (age_basis - policy.age) if policy.age else None
        version = policy.cutoff_version
        count = 0
        for tag in tags:
            if remove_arch_specific and tag.architecture:
                continue
            if tag.date and date and tag.date < date:
                continue
            if tag.version and version and tag.version < version:
                continue
            yield tag
            count += 1
            if policy.number and count >= policy.number:
                break

    def _first_tags(
        self,
        image_type: RSPImageType,
        total: int,
        *,
        remove_arch_specific: bool = True,
    ) -> Iterator[T]:
        """Get the first ``total`` tags by type.

        Parameters
        ----------
        image_type
            Type of tags to retrieve.
        total
            Total number of tags to retrieve. The result may be shorter if
            fewer than that may tags are available.
        remove_arch_specific
            If `True`, filter out all tags for a specific architecture and
            only include tags for all supported architectures.

        Yields
        ------
        RSPImageTag
            Tags satisfying the given criteria.
        """
        if total == 0 or image_type not in self._by_type:
            return
        count = 0
        for tag in self._by_type[image_type]:
            if remove_arch_specific and tag.architecture:
                continue
            yield tag
            count += 1
            if count >= total:
                return
