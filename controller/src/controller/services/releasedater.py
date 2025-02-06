"""Release tags on an image do not give us enough information to get its age.

However, release and release candidate images are always associated with a
tag in lsst/lsst_distrib, and the image should have been built not long after
that tag was set.  Those are always annotated tags, which come with date
information.

This is simply a caching service to be able to ascertain an RSP image's age by
matching the RSP tag to an lsst_distrib tag and using that tag's date.
"""

import json
import os
import re
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from ..models.domain.rsptag import TAG_REGEXES, RSPImageTag, RSPImageType

DATEFMT = "%a %b %d %H:%M:%S %Y %z"


class ReleaseDater:
    """Simple caching service to map RSP image tags to release dates.

    For release and release candidate images, attempt to ascertain the
    matching lsst_distrib tag, and use its creation date as the image date.
    """

    def __init__(
        self,
        cachefile: Path,
        *,
        tag_source: str = "https://github.com/lsst/lsst_distrib",
        no_update: bool = False,
    ) -> None:
        self._cache: dict[str, datetime] = {}
        self._negativecache: set[str] = set()
        self._tag_source = tag_source
        self._no_update = no_update

        self._cachefile = cachefile
        self._read_cache()

    @staticmethod
    def _convert_rsp_to_distrib(rsptag: RSPImageTag) -> str | None:
        # We have an RSP image; we want to match it with the corresponding
        # lsst_distrib git tag if we can.  If we cannot, return None.
        #
        # We only care about doing this for releases and release candidates.
        ok_types = (RSPImageType.RELEASE, RSPImageType.CANDIDATE)
        if rsptag.image_type not in ok_types:
            return None
        match: re.Match | None = None
        if rsptag.image_type == RSPImageType.RELEASE:
            for img_type, regex in TAG_REGEXES:
                if img_type == rsptag.image_type:
                    match = regex.match(rsptag.tag)
                    if match:
                        break
        if match is None:
            return None
        # We have a match object, with named components.  Now we stitch that
        # into a string matching an lsst_distrib tag.
        tagdata = match.groupdict()
        # We know we have a major and minor version for all of our tags.
        # If accessing the key directly causes an error, something went badly
        # wrong.
        major = tagdata["major"]
        minor = tagdata["minor"]
        patch = tagdata.get("patch")
        if rsptag.image_type == RSPImageType.RELEASE:
            # If we only have these two, we have an ancient release version.
            # 17.0 was the last two-part version number. (There were also
            # four-part version numbers, but those ended with 8.0.0.0,
            # which was long before we built RSP images).
            if not patch:
                return f"{major}.{minor}"
            return f"{major}.{minor}.{patch}"
        # Now we know we have a release candidate.
        # In the RSP's lifetime, there have been release candidates that
        # only had two version parts, but TAG_REGEXES doesn't match them,
        # so we conclude we don't care (they're from 2019 at latest, so
        # wouldn't run in any event in 2025 or later).  We don't seem to
        # have these RSP images anymore, or if we do, we're categorizing them
        # as "unknown" (since they won't match the candidate
        # regular expression).
        pre = tagdata.get("pre")
        return f"v{major}.{minor}.{patch}.rc{pre}"

    @staticmethod
    def _filter_distrib_tag(inp: str) -> str | None:
        # This is a dumb and not quite accurate tag heuristic (there are two
        # tags that start with "2015" and "2016" that are not release/rc tags)
        # but it's an adequate first-pass filter.
        #
        # Because of the git for-each-ref, it should always start with
        # "refs/tags/" but just in case...
        reftxt = "refs/tags/"
        if not inp.startswith(reftxt):
            return None
        # strip beginning, leaving just tag text
        tag = inp[len(reftxt) :]
        # Pass if it starts with "v" or a digit.  That's it.
        if tag.startswith("v"):
            return tag
        if re.match(r"\r+", tag):
            return tag
        # Not a release or rc tag
        return None

    def _read_cache(self) -> None:
        if self._cachefile.is_file():
            text = self._cachefile.read_text()
            if not text:
                return
            textcache = json.loads(text)
            self._cache = {
                x: datetime.strptime(textcache[x], DATEFMT).replace(tzinfo=UTC)
                for x in textcache
            }

    def _write_cache(self) -> None:
        textcache = {x: self._cache[x].strftime(DATEFMT) for x in self._cache}
        self._cachefile.write_text(json.dumps(textcache))

    def _read_tags_from_git(self) -> None:
        if self._no_update:
            return
        owd = Path.cwd
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(
                ["git", "clone", self._tag_source, "repo"],
                capture_output=True,
                check=True,
            )
            os.chdir(str(Path(td) / "repo"))
            result = subprocess.run(
                [
                    "git",
                    "for-each-ref",
                    "--format",
                    "%(refname):%(creatordate)",
                    "refs/tags/",
                ],
                capture_output=True,
                check=True,
                text=True,
            )
            rlines = result.stdout.split("\n")
            for rline in rlines:
                line = rline.rstrip()
                ref, strdate = line.split(":")
                stamp = datetime.strptime(strdate, DATEFMT).replace(tzinfo=UTC)
                tag = self._filter_distrib_tag(ref)
                if tag:
                    self._cache[tag] = stamp
        os.chdir(str(owd))
        self._write_cache()

    def get_release_date(self, img: RSPImageTag) -> datetime | None:
        """Get the release date, based on the tag, for an RSPImageTag.

        Parameters
        ----------
        img
            Image to try to determine creation date for.

        Returns
        -------
        datetime.datetime | None
            Image creation date, or None if it cannot be determined.
        """
        tag = img.tag
        if tag in self._negativecache:
            return None
        distrib_tag = self._convert_rsp_to_distrib(img)
        if distrib_tag is None:
            return None
        release_date = self._cache.get(distrib_tag)
        if release_date is not None:
            return release_date
        # It doesn't match--perhaps the tag has appeared since we last
        # updated the cache?
        #
        # Force an update.
        self._read_tags_from_git()
        release_date = self._cache.get(distrib_tag)
        if release_date is None:
            # Nope, there's just no mapping for it.  Cache that result too.
            self._negativecache.add(tag)
            return None
        return release_date
