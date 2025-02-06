"""Test release date caching lookup engine."""

from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from controller.models.domain.rsptag import RSPImageTag
from controller.services.releasedater import ReleaseDater


def test_releasedater() -> None:
    with TemporaryDirectory() as td:
        release_text = (
            Path(__file__).parent.parent
            / "data"
            / "releasedater"
            / "releases.json"
        ).read_text()
        cachefile = Path(td) / "releases.json"
        cachefile.write_text(release_text)

        rd = ReleaseDater(cachefile=cachefile, no_update=True)

        assert not rd._negativecache

        expected = {
            "r130": datetime(2017, 2, 28, 4, 5, 22, tzinfo=UTC),
            "r17_0_1": datetime(2019, 3, 20, 17, 45, 37, tzinfo=UTC),
            "r28_0_1": datetime(2025, 2, 4, 15, 13, 2, tzinfo=UTC),
            "r27_0_0_rc3": datetime(2024, 6, 6, 1, 23, 47, tzinfo=UTC),
            "exp_r28_0_0_rc2_py": datetime(2024, 12, 6, 17, 2, 14, tzinfo=UTC),
            "w_2025_01": None,
            "unknown_tag": None,
        }

        for tagstr, datestamp in expected.items():
            tag = RSPImageTag.from_str(tagstr)
            assert rd.get_release_date(tag) == datestamp
