"""Classes to hold all the semantic data and metadata we can extract from a
tag.  Mostly simplified from cachemachine's implementation.

These are specific to the Rubin Science Platform tag conventions.  The tag
must be in the format specified by https://sqr-059.lsst.io"""

import re
from dataclasses import dataclass, field
from enum import IntEnum, auto
from typing import Dict, List, Match, Optional, Tuple

from semver import VersionInfo

from ..exceptions import IncomparableImageTypesError
from .v1.prepuller import Image


class RSPTagType(IntEnum):
    """Enum specifying different tag types for Rubin Science Platform Lab
    images.

    These are listed in reverse order of priority to make construction of
    display name lists trivial: tags in higher categories will be listed
    before those in lower categories.
    """

    UNKNOWN = auto()
    EXPERIMENTAL = auto()
    RELEASE_CANDIDATE = auto()
    DAILY = auto()
    WEEKLY = auto()
    RELEASE = auto()
    ALIAS = auto()


DOCKER_DEFAULT_TAG = "latest"

# Build the raw strings for tags and tag components, which can then be
# mixed and matched to some degree.  Cuts down a little on the complexity of
# the TAGTYPE_REGEXPS tuple and prevents some duplication.  We will use named
# group matches to make understanding the tag data easier.
TAG: Dict[str, str] = {
    # r22_0_1
    "release": r"r(?P<major>\d+)_(?P<minor>\d+)_(?P<patch>\d+)",
    # r23_0_0_rc1
    "rc": r"r(?P<major>\d+)_(?P<minor>\d+)_(?P<patch>\d+)_rc(?P<pre>\d+)",
    # w_2021_13
    "weekly": r"w_(?P<year>\d+)_(?P<week>\d+)",
    # d_2021_05_13
    "daily": r"d_(?P<year>\d+)_(?P<month>\d+)_(?P<day>\d+)",
    # exp_flattened_build
    "experimental": r"(?:exp)",
    # c0020.002
    "cycle": r"_(?P<ctag>c|csal)(?P<cycle>\d+)\.(?P<cbuild>\d+)",
    # _whatever_your_little_heart_desires
    "rest": r"_(?P<rest>.*)",
}

# This is the heart of the parser: it's an ordered list of tuples, each of
# which contains a tag type followed by a regular expression defining
# something that matches that type, with named capture groups.
#
# Note that this is matched top to bottom.  In particular, the release
# candidate images must precede the release images, because an RC candidate
# could be a release image with non-empty "rest".
#
TAGTYPE_REGEXPS: List[Tuple[RSPTagType, re.Pattern]] = [
    # r23_0_0_rc1_c0020.001_20210513
    (
        RSPTagType.RELEASE_CANDIDATE,
        re.compile(TAG["rc"] + TAG["cycle"] + TAG["rest"] + r"$"),
    ),
    # r23_0_0_rc1_c0020.001
    (
        RSPTagType.RELEASE_CANDIDATE,
        re.compile(TAG["rc"] + TAG["cycle"] + r"$"),
    ),
    # r23_0_0_rc1_20210513
    (
        RSPTagType.RELEASE_CANDIDATE,
        re.compile(TAG["rc"] + TAG["rest"] + r"$"),
    ),
    # r23_0_0_rc1
    (RSPTagType.RELEASE_CANDIDATE, re.compile(TAG["rc"] + r"$")),
    # r22_0_1_c0019.001_20210513
    (
        RSPTagType.RELEASE,
        re.compile(TAG["release"] + TAG["cycle"] + TAG["rest"] + r"$"),
    ),
    # r22_0_1_c0019.001
    (RSPTagType.RELEASE, re.compile(TAG["release"] + TAG["cycle"] + r"$")),
    # r22_0_1_20210513
    (RSPTagType.RELEASE, re.compile(TAG["release"] + TAG["rest"] + r"$")),
    # r22_0_1
    (RSPTagType.RELEASE, re.compile(TAG["release"] + r"$")),
    # r170 (obsolete) (no new ones, no additional parts)
    (RSPTagType.RELEASE, re.compile(r"r(?P<major>\d\d)(?P<minor>\d)$")),
    # w_2021_13_c0020.001_20210513
    (
        RSPTagType.WEEKLY,
        re.compile(TAG["weekly"] + TAG["cycle"] + TAG["rest"] + r"$"),
    ),
    # w_2021_13_c0020.001
    (RSPTagType.WEEKLY, re.compile(TAG["weekly"] + TAG["cycle"] + r"$")),
    # w_2021_13_20210513
    (RSPTagType.WEEKLY, re.compile(TAG["weekly"] + TAG["rest"] + r"$")),
    # w_2021_13
    (RSPTagType.WEEKLY, re.compile(TAG["weekly"] + r"$")),
    # d_2021_05_13_c0019.001_20210513
    (
        RSPTagType.DAILY,
        re.compile(TAG["daily"] + TAG["cycle"] + TAG["rest"] + r"$"),
    ),
    # d_2021_05_13_c0019.001
    (RSPTagType.DAILY, re.compile(TAG["daily"] + TAG["cycle"] + r"$")),
    # d_2021_05_13_20210513
    (RSPTagType.DAILY, re.compile(TAG["daily"] + TAG["rest"] + r"$")),
    # d_2021_05_13
    (RSPTagType.DAILY, re.compile(TAG["daily"] + r"$")),
    # exp_w_2021_05_13_nosudo
    (
        RSPTagType.EXPERIMENTAL,
        re.compile(TAG["experimental"] + TAG["rest"] + r"$"),
    ),
]


@dataclass
class StandaloneRSPTag:
    """The primary method of construction of a StandaloneRSPTag is the
    parse_tag classmethod.  The StandaloneRSPTag holds only the data that comes
    from the tag text.

    In order to construct a complete RSPTag, which would contain the Docker
    path, the digest, and the preferred tag and display name, the
    StandaloneRSPTag must be augmented with data that must be supplied by
    a Docker repository and does not exist in the tag text."""

    tag: str
    """This is the tag on a given image.  We assume there is one and
    only one Docker path for all our tags.  If we need access to
    multiple image names, repositories, or hosts, we will need a
    different strategy.

    example: w_2021_22
    """

    image_type: RSPTagType
    """Rubin-specific RSP Lab image type.

    example: RSPTagType.WEEKLY
    """

    display_name: str
    """Human-readable display name corresponding to a tag.

    example: Weekly 2021_22
    """

    semantic_version: Optional[VersionInfo]
    """Semantic version constructed from a tag.  Only extant for Daily,
    Weekly, Release, and Release Candidate image types.  Only meaningful for
    comparison within a type.

    example: VersionInfo(2021,22,0)
    """

    cycle: Optional[int]
    """XML Cycle for a given image.  Only used in T&S builds.

    example: 20
    """

    # Required for SemanticVersion
    class Config:
        arbitrary_types_allowed = True

    @classmethod
    def parse_tag(
        cls,
        tag: str,
    ) -> "StandaloneRSPTag":
        if not tag:
            tag = DOCKER_DEFAULT_TAG  # This is a Docker convention
        for (tagtype, regexp) in TAGTYPE_REGEXPS:
            match = re.compile(regexp).match(tag)
            if not match:
                continue
            display_name, semver, cycle = StandaloneRSPTag.extract_metadata(
                match=match, tag=tag, tagtype=tagtype
            )
            return cls(
                tag=tag,
                image_type=tagtype,
                display_name=display_name,
                semantic_version=semver,
                cycle=cycle,
            )
        # Didn't find any matches
        return cls(
            tag=tag,
            image_type=RSPTagType.UNKNOWN,
            display_name=tag,
            semantic_version=None,
            cycle=None,
        )

    """Some static methods that are used, ultimately, by parse_tag.
    """

    @staticmethod
    def prettify_tag(tag: str) -> str:
        """Little convenience wrapper for turning
        (possibly-underscore-separated) tags into prettier space-separated
        title case."""
        return tag.replace("_", " ").title()

    @staticmethod
    def extract_metadata(
        match: Match,
        tag: str,
        tagtype: RSPTagType,
    ) -> Tuple[str, Optional[VersionInfo], Optional[int]]:
        """Return a display name, semantic version (optional), and cycle
        (optional) from match, tag, and type."""
        md = match.groupdict()
        name = tag
        semver = None
        ctag = md.get("ctag")
        cycle = md.get("cycle")
        cbuild = md.get("cbuild")
        cycle_int = None
        rest = md.get("rest")
        # We have our defaults.  The rest is optimistically seeing if we can
        # do better
        if tagtype == RSPTagType.UNKNOWN:
            # We can't do anything better, but we really shouldn't be
            # extracting from an unknown type.
            pass
        elif tagtype == RSPTagType.EXPERIMENTAL:
            # This one is slightly complicated.  Because of the way the build
            # process works, our tag likely looks like exp_<other-legal-tag>.
            # So we try that hypothesis.  If that's not how the tag is
            # constructed, nname will just come back as everything
            # after "exp_".
            if rest is not None:
                # it actually never will be None if the regexp matched, but
                # mypy doesn't know that
                temp_ptag = StandaloneRSPTag.parse_tag(rest)
                # We only care about the display name, not any other fields.
                name = f"Experimental {temp_ptag.display_name}"
        else:
            # Everything else does get an actual semantic version
            build = StandaloneRSPTag.trailing_parts_to_semver_build_component(
                cycle, cbuild, ctag, rest
            )
            typename = StandaloneRSPTag.prettify_tag(tagtype.name)
            restname = name[2:]
            if (
                tagtype == RSPTagType.RELEASE
                or tagtype == RSPTagType.RELEASE_CANDIDATE
            ):
                # This is bulky because we don't want to raise an error here
                # if we cannot extract a required field; instead we let the
                # field be None, and then the semantic version construction
                # fails later.  That's OK too, because we try that in a
                # try/expect block and return None if we can't construct
                # a version.  In *that* case we have a tag without semantic
                # version information--which is allowable.
                major = StandaloneRSPTag.maybe_int(md.get("major"))
                minor = StandaloneRSPTag.maybe_int(md.get("minor"))
                patch = StandaloneRSPTag.maybe_int(
                    md.get("patch", "0")
                )  # If omitted, it's zero
                restname = f"r{major}.{minor}.{patch}"
                pre = md.get("pre")
                if pre:
                    pre = f"rc{pre}"
                    restname += f"-{pre}"
            else:  # tagtype is weekly or daily
                year = md.get("year")
                month = md.get("month")
                week = md.get("week")
                day = md.get("day")
                major = StandaloneRSPTag.maybe_int(year)
                if tagtype == RSPTagType.WEEKLY:
                    minor = StandaloneRSPTag.maybe_int(week)
                    patch = 0
                    restname = (
                        f"{year}_{week}"  # preserve initial string format
                    )
                else:
                    minor = StandaloneRSPTag.maybe_int(md.get("month"))
                    patch = StandaloneRSPTag.maybe_int(md.get("day"))
                    restname = (
                        f"{year}_{month}_{day}"  # preserve string format
                    )
                pre = None
            try:
                semver = VersionInfo(
                    major=major,
                    minor=minor,
                    patch=patch,
                    prerelease=pre,
                    build=build,
                )
            except TypeError:
                pass
            name = f"{typename} {restname}"  # Glue together display name.
            if cycle:
                name += f" (SAL Cycle {cycle}, Build {cbuild})"
            if rest:
                name += f" [{rest}]"
            cycle_int = StandaloneRSPTag.maybe_int(cycle)
        return (name, semver, cycle_int)

    @staticmethod
    def maybe_int(n: Optional[str]) -> Optional[int]:
        if n is None:
            return None
        return int(n)

    @staticmethod
    def trailing_parts_to_semver_build_component(
        cycle: Optional[str],
        cbuild: Optional[str],
        ctag: Optional[str],  # if present, either 'c' or 'csal'
        rest: Optional[str] = None,
    ) -> Optional[str]:
        """This takes care of massaging the cycle components, and 'rest', into
        a semver-compatible buildstring, which is dot-separated and can only
        contain alphanumerics.  See SQR-059 for how it's used.
        """
        if cycle:
            if rest:
                # Cycle must always precede rest
                rest = f"{ctag}{cycle}.{cbuild}_{rest}"
            else:
                rest = f"{ctag}{cycle}.{cbuild}"
        # We're done with cycle components now.
        if not rest:
            return None
        rest = rest.replace("_", ".")
        pat = re.compile(r"[^\w|\.]+")  # Identify all non alphanum, non-dots
        # Throw away all of those after turning underscores to dots.
        rest = pat.sub("", rest)
        if not rest:  # if we are left with an empty string, return None
            return None
        return rest

    def compare(self, other: "StandaloneRSPTag") -> int:
        """This is modelled after semver.compare, but raises an exception
        if the images do not have the same image_type."""
        if self.image_type != other.image_type:
            raise IncomparableImageTypesError(
                f"RSPTag '{self.tag}' of type {self.image_type} cannot be "
                + f"compared to '{other.tag}' of type {other.image_type}."
            )
        # The easy case: we have a type with a semantic_version attribute.
        # Use it.
        if (
            self.semantic_version is not None
            and other.semantic_version is not None
        ):
            return self.semantic_version.compare(other.semantic_version)
        # Otherwise, all we can do is sort lexigraphically by tag.
        # Experimentals can be sorted only by tag.
        if self.tag == other.tag:
            return 0
        if self.tag < other.tag:
            return -1
        return 1

    """Implement comparison operators."""

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, StandaloneRSPTag):
            return NotImplemented
        return self.compare(other) == 0

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)

    def __gt__(self, other: "StandaloneRSPTag") -> bool:
        return self.compare(other) == 1

    def __le__(self, other: "StandaloneRSPTag") -> bool:
        return not self.__gt__(other)

    def __lt__(self, other: "StandaloneRSPTag") -> bool:
        return self.compare(other) == -1

    def __ge__(self, other: "StandaloneRSPTag") -> bool:
        return not self.__lt__(other)


@dataclass
class RSPTag(StandaloneRSPTag):
    """The primary method of RSPTag construction
    is the from_tag classmethod.  The RSPTag holds all the metadata
    encoded within a particular tag (in its base class) and also additional
    metadata known and/or calculated via outside sources: the
    image digest, whether the tag is a known alias, and the image reference.
    """

    image_ref: str
    """This is the Docker reference for this particular image.  It's not
    actually used within this class, but it's useful as general image
    metadata, since it's required to pull the image.

    example: index.docker.io/lsstsqre/sciplat-lab:w_2021_22
    """

    digest: str
    """Image digest for a particular image.  It is required, because without
    it, you might as well use a StandaloneRSPTag.

    example: ("sha256:419c4b7e14603711b25fa9e0569460a753"
              "c4b2449fe275bb5f89743b01794a30")
    """

    size: Optional[int]
    """Size in bytes for a particular image.  ``None`` if unknown.
    """

    alias_tags: List[str]
    """List of known aliases for this tag.
    """

    nodes: List[str]
    """List of names of nodes to which the image corresponding to the tag
    is pulled.
    """

    # We use a classmethod here rather than just allowing specification of
    # the fields because we generally want to derive most of our attributes.
    @classmethod
    def from_tag(
        cls,
        tag: str,
        digest: str,
        image_ref: str = "",
        alias_tags: List[str] = list(),
        nodes: List[str] = list(),
        override_name: str = "",
        override_cycle: Optional[int] = None,
        size: Optional[int] = None,
    ) -> "RSPTag":
        """Create a RSPTag object from a tag and a list of alias tags.
        Allow overriding name rather than generating one, and allow an
        optional digest parameter."""
        if not digest:
            raise RuntimeError("A digest is required to create an RSPTag")
        partial_tag = StandaloneRSPTag.parse_tag(tag)
        image_type = partial_tag.image_type
        display_name = partial_tag.display_name
        cycle = partial_tag.cycle
        # Here's where we glue in the alias knowledge.  Note that we just
        # special-case "latest" and "latest_<anything>"
        if tag in alias_tags or tag == "latest" or tag.startswith("latest_"):
            image_type = RSPTagType.ALIAS
            display_name = StandaloneRSPTag.prettify_tag(tag)
        # And here we override the name if appropriate.
        if override_name:
            display_name = override_name
        # Override cycle if appropriate
        if override_cycle:
            cycle = override_cycle
        return cls(
            tag=tag,
            image_ref=image_ref,
            digest=digest,
            size=size,
            image_type=image_type,
            display_name=display_name,
            semantic_version=partial_tag.semantic_version,
            cycle=cycle,
            alias_tags=alias_tags,
            nodes=nodes,
        )

    def is_recognized(self) -> bool:
        """Only return true if the image is a known type that is not known
        to be an alias.  It's possible that we also want to exclude
        experimental images.
        """
        img_type = self.image_type
        unrecognized = (RSPTagType.UNKNOWN, RSPTagType.ALIAS)
        if img_type in unrecognized:
            return False
        return True


@dataclass
class RSPTagList:
    """This is a class to hold tag objects and return sorted lists of their
    corresponding Image objects for construction of the image menu.
    """

    all_tags: List[RSPTag] = field(default_factory=list)

    def sort_all_tags(self) -> None:
        """This sorts the ``all_tags`` field according to the ordering of
        the RSPTagType enum."""
        new_tags: Dict[RSPTagType, List[RSPTag]] = dict()
        for tag_type in RSPTagType:  # Initialize the dict, relying on the fact
            # that dicts are insertion-ordered in Python 3.6+ (we require
            # 3.10 for TypeAlias, so this is safe)
            new_tags[tag_type] = list()
        for tag in self.all_tags:
            new_tags[tag.image_type].append(tag)
        # Now sort the tags within each type in reverse lexical order.  This
        # will sort them with most recent first, because of the tag type
        # definitions in SQR-059.
        for tag_type in RSPTagType:
            new_tags[tag.image_type].sort(reverse=True)
        # And flatten it out into a homogeneous list.
        flat_tags: List[RSPTag] = list()
        for k in new_tags:
            flat_tags.extend(new_tags[k])
        self.all_tags = flat_tags

    def to_imagelist(self) -> List[Image]:
        image_list: List[Image] = list()
        for t in self.all_tags:
            image_list.append(
                Image(
                    path=t.image_ref,
                    digest=t.digest,
                    name=t.display_name,
                    tags={t.tag: t.display_name},
                )
            )
        return image_list
