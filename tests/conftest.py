"""pytest fixtures for Nublado tests."""

from pathlib import Path

import pytest
import respx
from rubin.repertoire import Discovery, register_mock_discovery

from .support.data import NubladoData


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--update-test-data",
        action="store_true",
        default=False,
        help="Overwrite expected test output with current results",
    )


@pytest.fixture
def data(request: pytest.FixtureRequest) -> NubladoData:
    update = request.config.getoption("--update-test-data")
    return NubladoData(Path(__file__).parent / "data", update_test_data=update)


@pytest.fixture(autouse=True)
def mock_discovery(
    respx_mock: respx.Router, monkeypatch: pytest.MonkeyPatch
) -> Discovery:
    monkeypatch.setenv("REPERTOIRE_BASE_URL", "https://example.com/repertoire")
    path = Path(__file__).parent / "data" / "discovery.json"
    return register_mock_discovery(respx_mock, path)
