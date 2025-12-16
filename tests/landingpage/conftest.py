"""Pytest configuration and fixtures for landing page provisioner."""

from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest


# Things for startup/landing_page.
@pytest.fixture(scope="session")
def monkeysession() -> Iterator[pytest.MonkeyPatch]:
    """MonkeyPatch, but session-scoped."""
    mpatch = pytest.MonkeyPatch()
    yield mpatch
    mpatch.undo()


@pytest.fixture(scope="session")
def _init_container_fake_root(
    monkeysession: pytest.MonkeyPatch,
) -> Iterator[None]:
    with TemporaryDirectory() as td:
        contents = {
            "hello.txt": "Hello, world!\n",
            "goodbye.txt": "Goodbye, cruel world.\n",
        }
        tutorial_directory = Path(td) / "tutorials"
        tutorial_directory.mkdir(parents=True)
        for fn, text in contents.items():
            out_file = tutorial_directory / fn
            out_file.write_text(text)
        home_directory = Path(td) / "home" / "gregorsamsa"
        home_directory.mkdir(parents=True)

        monkeysession.setenv("NUBLADO_HOME", str(home_directory))
        monkeysession.setenv(
            "CST_LANDING_PAGE_SRC_DIR", str(tutorial_directory)
        )
        monkeysession.setenv("CST_LANDING_PAGE_TGR_DIR", "notebooks/tutorials")
        monkeysession.setenv(
            "CST_LANDING_PAGE_FILES", "hello.txt", "goodbye.txt"
        )
        yield
