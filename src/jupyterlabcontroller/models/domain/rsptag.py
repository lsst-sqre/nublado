"""Abstract data type for handling RSP image tags."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from functools import total_ordering
from typing import Self

from semver import VersionInfo

__all__ = [
    "DOCKER_DEFAULT_TAG",
    "RSPImageTag",
    "RSPImageType",
]

DOCKER_DEFAULT_TAG = "latest"
"""Implicit tag used by Docker/Kubernetes when no tag is specified."""


class RSPImageType(Enum):
    """The type (generally, release series) of the identified image.

    This is listed in order of priority when constructing menus.  The image
    types listed first will be shown earlier in the menu.
    """

    ALIAS = "Alias"
    RELEASE = "Release"
    WEEKLY = "Weekly"
    DAILY = "Daily"
    CANDIDATE = "Release Candidate"
    EXPERIMENTAL = "Experimental"
    UNKNOWN = "Unknown"


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
# _whatever_your_little_heart_desires
_REST = r"_(?P<rest>.*)"

# The heart of the parser.  An ordered list of tuples, each of which contains
# a tag type followed by a regular expression defining something that matches
# that type, with named capture groups.
#
# Note that this is matched top to bottom.  In particular, the release
# candidate images must precede the release images since they would otherwise
# parse as a release image with non-empty "rest".
_TAG_REGEXES = [
    # r23_0_0_rc1_c0020.001_20210513
    (RSPImageType.CANDIDATE, re.compile(_CANDIDATE + _CYCLE + _REST + "$")),
    # r23_0_0_rc1_c0020.001
    (RSPImageType.CANDIDATE, re.compile(_CANDIDATE + _CYCLE + "$")),
    # r23_0_0_rc1_20210513
    (RSPImageType.CANDIDATE, re.compile(_CANDIDATE + _REST + "$")),
    # r23_0_0_rc1
    (RSPImageType.CANDIDATE, re.compile(_CANDIDATE + "$")),
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
    # w_2021_13_c0020.001_20210513
    (RSPImageType.WEEKLY, re.compile(_WEEKLY + _CYCLE + _REST + "$")),
    # w_2021_13_c0020.001
    (RSPImageType.WEEKLY, re.compile(_WEEKLY + _CYCLE + "$")),
    # w_2021_13_20210513
    (RSPImageType.WEEKLY, re.compile(_WEEKLY + _REST + "$")),
    # w_2021_13
    (RSPImageType.WEEKLY, re.compile(_WEEKLY + "$")),
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
]


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

    version: VersionInfo | None
    """Version information as a semantic version."""

    cycle: int | None
    """XML schema version implemented by this image (only for T&S builds)."""

    display_name: str
    """Human-readable display name."""

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
                try:
                    return cls._from_match(image_type, match, tag)
                except Exception:
                    # It should be impossible for from_match to fail if we
                    # constructed the regexes properly, but if it does,
                    # silently fall back on treating this as an unknown tag
                    # rather than crashing the lab controller.
                    pass

        # No matches, so return the unknown tag type.
        return cls(
            image_type=RSPImageType.UNKNOWN,
            version=None,
            tag=tag,
            cycle=None,
            display_name=tag,
        )

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
        """Helper function to create an `RSPImageTag` from a regex match.

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
                version=None,
                tag=tag,
                cycle=None,
                display_name=display_name,
            )

        # Determine the build number, the last component of the semantic
        # version, which is the same for all image types.
        build = cls._determine_build(cycle, cbuild, rest)

        # The display name starts as the image type and we add more
        # information as we go.
        display_name = image_type.value

        # The rest of the semantic version depends on the image type.
        if image_type in (RSPImageType.RELEASE, RSPImageType.CANDIDATE):
            major = data["major"]
            minor = data["minor"]
            patch = data.get("patch", "0")
            pre = data.get("pre")
            display_name += f" r{major}.{minor}.{patch}"
            if pre:
                display_name += "-" + pre
        else:
            major = data["year"]
            if image_type == RSPImageType.WEEKLY:
                minor = data["week"]
                patch = "0"
                display_name += f" {major}_{minor}"
            else:
                minor = data["month"]
                patch = data["day"]
                display_name += f" {major}_{minor}_{patch}"
            pre = None

        # Construct the semantic version.  It should be impossible, given our
        # regexes, for this to fail, but if it does that's handled in from_str.
        version = VersionInfo(int(major), int(minor), int(patch), pre, build)

        # If there is extra information, add it to the end of the display name.
        if cycle:
            display_name += f" (SAL Cycle {cycle}, Build {cbuild})"
        if rest:
            display_name += f" [{rest}]"

        # Return the results.
        return cls(
            image_type=image_type,
            version=version,
            tag=tag,
            cycle=int(cycle) if cycle else None,
            display_name=display_name,
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
        if not isinstance(other, RSPImageTag):
            return NotImplemented
        if self.image_type != other.image_type:
            return NotImplemented
        if self.version and other.version:
            return self.version.compare(other.version)
        if self.tag == other.tag:
            return 0
        return -1 if self.tag < other.tag else 1
