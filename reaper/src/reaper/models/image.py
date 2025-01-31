"""Model for necessary information about container images."""

import datetime
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from functools import total_ordering
from typing import Self, cast

import semver

from .rsptag import (
    RSP_TYPENAMES,
    RSPImageTag,
    RSPImageTagCollection,
    RSPImageType,
)

DATEFMT = "%Y-%m-%dT%H:%M:%S.%f%z"
LATEST_TAGS = ("latest", "latest_release", "latest_weekly", "latest_daily")

type JSONImage = dict[str, str | int | list[str] | None]

type ImageSpec = dict[str, Image] | str | Image | list[str] | list[Image]


class ImageVersionClass(Enum):
    """Tagged images are versioned with either RSP tags or semver tags."""

    RSP = "rsp"
    SEMVER = "semver"
    UNTAGGED = "untagged"


@total_ordering
@dataclass
class Image:
    """Class representing the things about an OCI image we care about.

    This actually has to be a superset of those things, and some will be
    optional.  Case in point: you need the image ID (an integer) to do
    package deletion at ghcr.io.  But at other sites, there's no such
    thing.
    """

    digest: str
    tags: set[str] = field(default_factory=set)
    date: datetime.datetime | None = None
    id: int | None = None
    rsp_image_tag: RSPImageTag | None = None
    semver_tag: semver.VersionInfo | None = None
    version_class: ImageVersionClass | None = None

    def __str__(self) -> str:
        """Pretty(?)-printed version.  Humans care about tags, and digests
        not so much.
        """
        colon_pos = self.digest.find(":")
        dig = self.digest
        if colon_pos > -1:
            dig = self.digest[1 + colon_pos :]
        if len(dig) > 8:
            dig = dig[:8] + "..."
        dig = f"<{dig}>"
        if (
            self.version_class == ImageVersionClass.SEMVER
            and self.semver_tag is not None
        ):
            tag = self.semver_tag
            vstr = f"{tag.major}.{tag.minor}.{tag.patch}"
            if tag.prerelease:
                vstr += f"-{tag.prerelease}"
            if tag.build:
                vstr += f"+{tag.build}"
            return f"[{vstr}] {self.digest}"
        elif (
            self.version_class == ImageVersionClass.RSP
            and self.rsp_image_tag is not None
        ):
            return f"[{self.rsp_image_tag.tag}] {dig}"
        return f"[<untagged>] {dig}"

    def __eq__(self, other: object) -> bool:
        return self._compare(other) == 0

    def __lt__(self, other: object) -> bool:
        order = self._compare(other)
        if order is NotImplemented:
            return NotImplemented
        return order == -1

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

        Notes
        -----
        First, images with the same digest are the same image.

        Beyond that, Images are only comparable if they are the same tag type
        (RSPTag, Semver, or untagged).  Further, if they are RSPTag images,
        they are only comparable within a category (weekly, release, etc).

        Untagged images are only sorted by date, and failing that, digest.
        """
        if not isinstance(other, Image):
            return NotImplemented

        if self.digest == other.digest:
            # Tags are not relevant.  It's the same image.
            return 0

        return self._compare_by_class(other)

    def _compare_by_class(self, other_image: Self) -> int:
        myclass = self.version_class
        otherclass = other_image.version_class

        if myclass == otherclass:
            if myclass == ImageVersionClass.RSP:
                return self._compare_rsptags(other_image)
            elif myclass == ImageVersionClass.SEMVER:
                return self._compare_semver(other_image)
            else:
                return self._compare_dates(other_image)
        else:
            return NotImplemented

    def _compare_rsptags(self, other_image: Self) -> int:
        if self.rsp_image_tag is None:
            raise ValueError(f"{self} rsp_image_tag cannot be None")
        if other_image.rsp_image_tag is None:
            raise ValueError(f"{other_image} rsp_image_tag cannot be None")
        return self.rsp_image_tag.compare(other_image.rsp_image_tag)

    def _compare_semver(self, other_image: Self) -> int:
        if self.semver_tag is None:
            raise ValueError(f"{self} semver_tag cannot be None")
        if other_image.semver_tag is None:
            raise ValueError(f"{other_image} semver_tag cannot be None")
        if self.semver_tag == other_image.semver_tag:
            return 0
        if self.semver_tag < other_image.semver_tag:
            return -1
        else:
            return 1

    def _compare_rsp_image_tags(self, other_tag: RSPImageTag) -> int:
        if self.rsp_image_tag is None:
            raise ValueError("rsp_image_tag is None")
        if self.rsp_image_tag < other_tag:
            return -1
        if self.rsp_image_tag > other_tag:
            return 1
        return 0

    def _compare_semver_tags(self, other_tag: semver.VersionInfo) -> int:
        if self.semver_tag is None:
            raise ValueError("semver_tag is None")
        if self.semver_tag < other_tag:
            return -1
        if self.semver_tag > other_tag:
            return 1
        return 0

    def _compare_dates(self, other: Self) -> int:
        if self.date and other.date:
            if self.date < other.date:
                return -1
            if self.date > other.date:
                return 1
            return 0
        if self.date and not other.date:
            return -1
        if other.date and not self.date:
            return 1
        return self._compare_digests(other)

    def _compare_digests(self, other: Self) -> int:
        if self.digest == other.digest:
            return 0
        if self.digest < other.digest:
            return -1
        return 1

    def to_dict(self) -> JSONImage:
        # Differs from asdict, in that set and datetime aren't
        # JSON-serializable, so we make them a list and a string.
        #
        # We will just drop the semver/RSP tag fields, and rebuild them
        # on load.
        self_dict = asdict(self)
        list_tags: list[str] = []
        if self.tags:
            list_tags = list(self.tags)
        self_dict["tags"] = list_tags
        if self.date is None:
            self_dict["date"] = None
        else:
            self_dict["date"] = self.date.strftime(DATEFMT)
        # Eliminate the reconstitutable fields
        for fld in ("rsp_image_tag", "semver_tag", "version_class"):
            if fld in self_dict:
                del self_dict[fld]
        return self_dict

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    def apply_best_tag(self) -> None:
        """Choose the best tag (preferring RSP to semver) for an image."""
        collection = RSPImageTagCollection.from_tag_names(
            list(self.tags), aliases=set(), cycle=None
        )
        self.rsp_image_tag = collection.best_tag()
        if self.rsp_image_tag is not None:
            self.semver_tag = self.rsp_image_tag.version
            if self.rsp_image_tag.image_type == RSPImageType.UNKNOWN:
                self.semver_tag = self._semver_from_tags()
        if self.semver_tag is None:
            self.semver_tag = self._generate_semver()

    def _semver_from_tags(self) -> semver.VersionInfo | None:
        raw_tags = list(self.tags)
        best_semver: semver.Version | None = None
        for tag in raw_tags:
            try:
                sv = semver.Version.parse(tag)
                if best_semver is None or best_semver < sv:
                    best_semver = sv
            except (ValueError, TypeError):
                continue
        return best_semver

    def _generate_semver(self) -> semver.VersionInfo:
        datestr = "unknown-date"
        if self.date is not None:
            datestr = (
                self.date.isoformat()
                .replace(":", "-")
                .replace("+", "plus")
                .replace(".", "-")
            )
        digstr = self.digest.replace(":", "-")
        return semver.Version.parse(f"0.0.0-{datestr}+{digstr}")

    @classmethod
    def from_json(cls, inp: JSONImage | str) -> Self:
        """Much painful assertion that each field is the right type."""
        if isinstance(inp, str):
            obj = json.loads(inp)
            inp = cast(JSONImage, obj)
        new_date: datetime.datetime | None = None
        if not isinstance(inp["digest"], str):
            raise TypeError(f"'digest' field of {inp} must be a string")
        if inp["date"] and isinstance(inp["date"], str):
            new_date = datetime.datetime.strptime(inp["date"], DATEFMT).replace(
                tzinfo=datetime.UTC
            )
        new_tags = set()
        t_s = inp["tags"]
        if t_s and not isinstance(t_s, str) and not isinstance(t_s, int):
            new_tags = set(t_s)
        new_id: int | None = None
        i_i = inp["id"]
        if i_i and isinstance(i_i, int):
            new_id = i_i
        new_obj = cls(digest=inp["digest"], tags=new_tags, date=new_date, id=new_id)
        new_obj.apply_best_tag()
        if not new_tags:
            new_obj.version_class = ImageVersionClass.UNTAGGED
        elif new_obj.rsp_image_tag is not None:
            new_obj.version_class = ImageVersionClass.RSP
        else:
            new_obj.version_class = ImageVersionClass.SEMVER
        return new_obj


def _gen_rsp_coll() -> dict[str, dict[str, Image]]:
    retval: dict[str, dict[str, Image]] = {}
    for typ in RSP_TYPENAMES:
        empty: dict[str, Image] = {}
        retval[typ] = empty
    return retval


@dataclass
class ImageCollection:
    """Class representing a categorized set of images. It turns out to
    be easier to make the 'rsp' field a dict rather than a dataclass for
    symmetry with the other two types.
    """

    untagged: dict[str, Image] = field(default_factory=dict)
    semver: dict[str, Image] = field(default_factory=dict)
    rsp: dict[str, dict[str, Image]] = field(default_factory=_gen_rsp_coll)

    def image_counts(self) -> dict[str, int]:
        retval: dict[str, int] = {}
        retval["untagged"] = len(self.untagged)
        retval["semver"] = len(self.semver)
        for typ in RSP_TYPENAMES:
            retval[f"rsp_{typ}"] = len(self.rsp[typ])
        return retval

    def remove_item(self, dig: str) -> None:
        if dig in self.untagged:
            del self.untagged[dig]
        if dig in self.semver:
            del self.semver[dig]
        for typ in RSP_TYPENAMES:
            if dig in self.rsp[typ]:
                del self.rsp[typ][dig]
